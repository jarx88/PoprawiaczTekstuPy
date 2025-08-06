# from .base_client import APIConnectionError, APIResponseError, DEFAULT_TIMEOUT # Zakomentowano - nieużywane
import httpx
import json
import os
import sys
from httpx import HTTPError, TimeoutException
from utils.logger import log_api_error, log_connection_error, log_timeout_error, logger
from PyQt6.QtWidgets import QMessageBox
from gui.prompts import get_system_prompt
from .base_client import DEFAULT_TIMEOUT, QUICK_TIMEOUT, CONNECTION_TIMEOUT, DEFAULT_RETRIES, APITimeoutError

DEEPSEEK_API_ENDPOINT = "https://api.deepseek.com/chat/completions" # Standardowy endpoint

def show_connection_error():
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setWindowTitle("Błąd połączenia")
    msg.setText("Nie można nawiązać połączenia z serwerem API")
    msg.setInformativeText("Możliwe przyczyny:\n"
                          "1. Brak połączenia z internetem\n"
                          "2. Firewall lub antywirus blokuje połączenie\n"
                          "3. Brak uprawnień administratora\n\n"
                          "Rozwiązania:\n"
                          "1. Uruchom program jako administrator\n"
                          "2. Dodaj wyjątek w Firewallu Windows\n"
                          "3. Sprawdź ustawienia antywirusa")
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg.show()

def handle_api_error(e):
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
        logger.error(f"Błąd połączenia: {str(e)}")
        show_connection_error()
        return True
    return False

def correct_text_deepseek(api_key, model, text_to_correct, instruction_prompt, system_prompt):
    # Określenie stylu na podstawie zawartości instruction_prompt
    style = "prompt" if "prompt" in instruction_prompt.lower() else "normal"
    system_prompt = get_system_prompt(style)
    """Poprawia tekst używając DeepSeek API poprzez bezpośrednie zapytanie HTTP."""
    if not api_key:
        logger.error("Brak klucza API DeepSeek")
        return "Błąd: Klucz API DeepSeek nie został podany."
    if not model:
        logger.error("Brak modelu DeepSeek")
        return "Błąd: Model DeepSeek nie został określony."
    if not text_to_correct:
        logger.error("Brak tekstu do poprawy")
        return "Błąd: Brak tekstu do poprawy."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Łączenie promptów - DeepSeek oczekuje listy wiadomości
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{instruction_prompt}\n\n---\n{text_to_correct}\n---"}
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    try:
        # Usprawniony klient z lepszymi timeoutami
        with httpx.Client(
            timeout=httpx.Timeout(
                connect=CONNECTION_TIMEOUT,  # 5s na połączenie
                read=DEFAULT_TIMEOUT,        # 15s na odczyt
                write=CONNECTION_TIMEOUT,    # 5s na zapis
                pool=CONNECTION_TIMEOUT      # 5s na pool
            )
        ) as client:
            response = client.post(DEEPSEEK_API_ENDPOINT, headers=headers, json=payload)
            response.raise_for_status()

            response_data = response.json()

            if response_data.get("choices") and len(response_data["choices"]) > 0:
                message = response_data["choices"][0].get("message")
                if message and message.get("content"):
                    corrected_text = message["content"].strip()
                    return corrected_text
                else:
                    error_msg = "Brak treści w odpowiedzi API"
                    logger.error(f"{error_msg}. Response: {response_data}")
                    return f"Błąd DeepSeek: {error_msg}"
            else:
                error_detail = response_data.get("error", {}).get("message", "Brak szczegółów błędu")
                logger.error(f"Brak 'choices' w odpowiedzi API. Error: {error_detail}")
                return f"Błąd DeepSeek: Brak 'choices' w odpowiedzi API. Szczegóły: {error_detail}"

    except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        logger.error(f"Timeout DeepSeek API: {e}", exc_info=True)
        return f"Błąd: DeepSeek API nie odpowiada (timeout {DEFAULT_TIMEOUT}s). Spróbuj ponownie."
    except (HTTPError, TimeoutException, httpx.ConnectError) as e:
        if handle_api_error(e):
            return "Błąd połączenia z API. Sprawdź komunikat błędu."
        error_content = "Brak danych błędu"
        try:
            if hasattr(e, 'response'):
                error_content = e.response.json()
        except (json.JSONDecodeError, AttributeError):
            if hasattr(e, 'response'):
                error_content = e.response.text
        log_api_error("DeepSeek", e, getattr(e, 'response', None))
        return f"Błąd DeepSeek (HTTP {getattr(e, 'response', None) and e.response.status_code or 'N/A'}): {error_content}"
    
    except Exception as e:
        log_connection_error("DeepSeek", e)
        return f"Błąd DeepSeek (nieoczekiwany): {str(e)}"

if __name__ == '__main__':
    current_script_path = os.path.abspath(__file__)
    api_clients_dir = os.path.dirname(current_script_path)
    project_root_dir = os.path.dirname(api_clients_dir)
    if project_root_dir not in sys.path:
        sys.path.insert(0, project_root_dir)

    test_api_key = "YOUR_DEEPSEEK_API_KEY"  # Wstaw swój klucz API DeepSeek
    test_model = "deepseek-chat"            # lub "deepseek-coder"

    if test_api_key == "YOUR_DEEPSEEK_API_KEY" or not test_api_key:
        print("Aby przetestować, ustaw `test_api_key` oraz `test_model` w sekcji if __name__ == '__main__'.")
    else:
        sample_text = "To jest tekst z błendem ortograficznym i gramatycznym. Popraw go proszę."
        sample_instruction = "Popraw następujący tekst, zachowując jego formatowanie."
        sample_system_prompt = (
            'You are a virtual editor specializing in proofreading Polish texts. '
            'Your goal is to transform the provided text into correct, clear, and professional-sounding Polish, '
            # ... (reszta system promptu jak w innych klientach) ...
            '6. **Text Only**: As the result, return ONLY the final, corrected Polish text, without any additional comments, headers, or explanations.'
        )
        
        print(f"Wysyłanie zapytania do DeepSeek z modelem: {test_model}...")
        result = correct_text_deepseek(test_api_key, test_model, sample_text, sample_instruction, sample_system_prompt)
        print("--- Wynik z DeepSeek ---")
        print(result)
        print("------------------------") 