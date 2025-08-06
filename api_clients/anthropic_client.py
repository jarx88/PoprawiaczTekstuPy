# from .base_client import APIConnectionError, APIResponseError, DEFAULT_TIMEOUT # Zakomentowano - nieużywane w tym pliku
# import time # Usunięto - nieużywane
import anthropic
import os
import sys
import httpx
from httpx import HTTPError, TimeoutException
from utils.logger import log_api_error, log_connection_error, log_timeout_error, logger
from PyQt6.QtWidgets import QMessageBox
from gui.prompts import get_system_prompt
from .base_client import DEFAULT_TIMEOUT, QUICK_TIMEOUT, CONNECTION_TIMEOUT, DEFAULT_RETRIES, APITimeoutError

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
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, anthropic.APIConnectionError)):
        logger.error(f"Błąd połączenia: {str(e)}")
        show_connection_error()
        return True
    return False

def correct_text_anthropic(api_key, model, text_to_correct, instruction_prompt, system_prompt):
    # Określenie stylu na podstawie zawartości instruction_prompt
    style = "prompt" if "prompt" in instruction_prompt.lower() else "normal"
    system_prompt = get_system_prompt(style)
    """Poprawia tekst używając Anthropic API."""
    if not api_key:
        logger.warning("Próba użycia Anthropic API bez klucza.") # Logowanie ostrzeżenia
        return "Błąd: Klucz API Anthropic nie został podany."
    if not model:
        logger.warning("Próba użycia Anthropic API bez podania modelu.") # Logowanie ostrzeżenia
        return "Błąd: Model Anthropic nie został określony."
    if not text_to_correct:
        logger.warning("Próba użycia Anthropic API bez tekstu do poprawy.") # Logowanie ostrzeżenia
        return "Błąd: Brak tekstu do poprawy."

    logger.info(f"Wysyłanie zapytania do Anthropic API (model: {model}). Tekst: {text_to_correct[:50]}...") # Logowanie rozpoczęcia zapytania

    try:
        # Konfiguracja klienta z ulepszonymi timeoutami
        client = anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(
                timeout=httpx.Timeout(
                    connect=CONNECTION_TIMEOUT,  # 5s na połączenie
                    read=DEFAULT_TIMEOUT,        # 15s na odczyt
                    write=CONNECTION_TIMEOUT,    # 5s na zapis
                    pool=CONNECTION_TIMEOUT      # 5s na pool
                ),
                transport=httpx.HTTPTransport(retries=DEFAULT_RETRIES)
            )
        )

        user_message_content = f"{instruction_prompt}\n\n---\n{text_to_correct}\n---"

        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": user_message_content
                }
            ],
            timeout=DEFAULT_TIMEOUT  # Dodatkowy timeout na poziomie wywołania
        )

        if response.content and isinstance(response.content, list) and len(response.content) > 0:
            text_block = next((block for block in response.content if block.type == 'text'), None)
            if text_block:
                logger.info("Otrzymano poprawną odpowiedź od Anthropic API.") # Logowanie sukcesu
                corrected_text = text_block.text.strip()
                return corrected_text
            else:
                error_msg = "Nie otrzymano bloku tekstowego w odpowiedzi"
                log_api_error("Anthropic", error_msg) # Używamy log_api_error
                return f"Błąd: {error_msg} od Anthropic API."
        else:
            error_msg = "Nie otrzymano poprawnej odpowiedzi (brak contentu lub niepoprawny format)"
            log_api_error("Anthropic", error_msg) # Używamy log_api_error
            return f"Błąd: {error_msg} od Anthropic API."

    except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        logger.error(f"Timeout Anthropic API: {e}", exc_info=True)
        return f"Błąd: Anthropic API nie odpowiada (timeout {DEFAULT_TIMEOUT}s). Spróbuj ponownie."
    except (HTTPError, TimeoutException, anthropic.APIConnectionError) as e:
        if handle_api_error(e):
            return "Błąd połączenia z API. Sprawdź komunikat błędu."
        error_content = "Brak danych błędu"
        try:
            if hasattr(e, 'response'):
                error_content = e.response.json()
        except:
            if hasattr(e, 'response'):
                error_content = e.response.text
        log_api_error("Anthropic", e, getattr(e, 'response', None))
        return f"Błąd Anthropic (HTTP {getattr(e, 'response', None) and e.response.status_code or 'N/A'}): {error_content}"
    
    except anthropic.RateLimitError as e:
        log_api_error("Anthropic", e) # Używamy log_api_error
        return f"Błąd Anthropic (limit zapytań): {str(e)}"
    
    except anthropic.AuthenticationError as e:
        log_api_error("Anthropic", e) # Używamy log_api_error
        return f"Błąd Anthropic (autentykacja): Nieprawidłowy klucz API"
    
    except anthropic.APIStatusError as e:
        log_api_error("Anthropic", e, getattr(e, 'response', None)) # Używamy log_api_error z odpowiedzią
        return f"Błąd Anthropic (status API {getattr(e, 'status_code', 'N/A')}): {str(e)}"
    
    except Exception as e:
        log_api_error("Anthropic", e) # Używamy log_api_error dla nieoczekiwanych błędów
        return f"Błąd Anthropic (nieoczekiwany): {str(e)}"

if __name__ == '__main__':
    # --- Modyfikacja sys.path dla testowania bezpośredniego ---
    current_script_path = os.path.abspath(__file__)
    api_clients_dir = os.path.dirname(current_script_path)
    project_root_dir = os.path.dirname(api_clients_dir)
    if project_root_dir not in sys.path:
        sys.path.insert(0, project_root_dir)
    
    # Zakomentowany import, bo nie jest używany w tym pliku bezpośrednio
    # from api_clients.base_client import APIConnectionError, APIResponseError

    # --- PRZYKŁAD UŻYCIA ---
    test_api_key = "YOUR_ANTHROPIC_API_KEY"  # Wstaw swój klucz Anthropic
    # Przykładowe modele Claude 3: "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"
    test_model = "claude-3-7-sonnet-latest" # Wybierz model

    if test_api_key == "YOUR_ANTHROPIC_API_KEY" or not test_api_key:
        logger.info("Aby przetestować, ustaw `test_api_key` oraz `test_model` w sekcji if __name__ == '__main__'.") # Używamy loggera
    else:
        sample_text = "To jest tekst z błendem ortograficznym i gramatycznym. Popraw go proszę."
        sample_instruction = "Popraw następujący tekst, zachowując jego formatowanie."
        sample_system_prompt = (
            'You are a virtual editor specializing in proofreading Polish texts. '
            'Your goal is to transform the provided text into correct, clear, and professional-sounding Polish, '
            'eliminating all language errors. The input text will be in Polish. Instructions: '
            '1. **Error-Free**: Detect and correct ALL spelling, grammatical, punctuation, and stylistic errors. Focus on precision and compliance with Polish language standards. '
            '2. **Clarity and Conciseness**: Simplify complex sentences while preserving their technical meaning. Aim for clear and precise communication. Eliminate redundant words and repetitions. '
            '3. **IT Terminology**: Preserve original technical terms, proper names, acronyms, and code snippets, unless they contain obvious spelling mistakes. Do not change their meaning. '
            '4. **Professional Tone**: Give the text a professional yet natural tone. Avoid colloquialisms, but also excessive formality. '
            '5. **Formatting**: Strictly preserve the original text formatting: paragraphs, bulleted/numbered lists, indentations, bolding (if Markdown was used), and line breaks. '
            '6. **Text Only**: As the result, return ONLY the final, corrected Polish text, without any additional comments, headers, or explanations.'
        )

        logger.info(f"Wysyłanie zapytania do Anthropic z modelem: {test_model}...") # Używamy loggera
        result = correct_text_anthropic(test_api_key, test_model, sample_text, sample_instruction, sample_system_prompt)
        logger.info("--- Wynik z Anthropic ---") # Używamy loggera
        logger.info(result) # Używamy loggera
        logger.info("-------------------------") # Używamy loggera 