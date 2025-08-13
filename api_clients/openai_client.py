# from .base_client import APIConnectionError, APIResponseError, DEFAULT_TIMEOUT # Zakomentowano - nieużywane w tym pliku
import time # Dla symulacji opóźnienia
import openai
import os
import sys # Dodano import sys
import ssl
import httpx
from httpx import HTTPError, TimeoutException
# PyQt6 removed - using CustomTkinter GUI now
from gui.prompts import get_system_prompt
from .base_client import DEFAULT_TIMEOUT, QUICK_TIMEOUT, CONNECTION_TIMEOUT, DEFAULT_RETRIES, APITimeoutError

# Importujemy logger z odpowiedniego miejsca w strukturze projektu
# Zakładamy, że api_clients jest na tym samym poziomie co utils
# więc potrzebujemy .utils.logger
try:
    from utils.logger import logger
    from utils.config_manager import get_config_value
except ImportError:
    # Fallback logger w przypadku problemów z importem (np. bezpośrednie uruchamianie)
    import logging
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO) # Domyślny poziom dla fallbacka
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Klucz API OpenAI jest teraz przekazywany jako argument do funkcji,
# ale można też ustawić go globalnie przez zmienną środowiskową OPENAI_API_KEY
# Jeśli chcesz używać zmiennej środowiskowej, odkomentuj:
# openai.api_key = os.getenv("OPENAI_API_KEY")

# Tymczasowo usuwamy import relatywny, jeśli będziemy go potrzebować później, przywrócimy
# from .base_client import APIConnectionError, APIResponseError, DEFAULT_TIMEOUT

def show_connection_error():
    """Log connection error - GUI now handled by main application"""
    logger.error("Connection error - cannot connect to API server")
    logger.error("Possible causes: 1) No internet 2) Firewall blocking 3) API server down")

def handle_api_error(e):
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, openai.APIConnectionError)):
        logger.error(f"Błąd połączenia: {str(e)}")
        show_connection_error()
        return True
    return False

def correct_text_openai(api_key, model, text_to_correct, instruction_prompt, system_prompt):
    """Poprawia tekst używając OpenAI API."""
    if not api_key:
        logger.warning("Próba użycia OpenAI API bez klucza.") # Logowanie ostrzeżenia
        return "Błąd: Klucz API OpenAI nie został podany."
    if not model:
        logger.warning("Próba użycia OpenAI API bez podania modelu.") # Logowanie ostrzeżenia
        return "Błąd: Model OpenAI nie został określony."
    if not text_to_correct:
        logger.warning("Próba użycia OpenAI API bez tekstu do poprawy.") # Logowanie ostrzeżenia
        return "Błąd: Brak tekstu do poprawy."

    logger.info(f"Wysyłanie zapytania do OpenAI API (model: {model}). Tekst: {text_to_correct[:50]}...") # Logowanie rozpoczęcia zapytania

    try:
        # Inicjalizacja klienta OpenAI z ulepszoną konfiguracją
        client = openai.OpenAI(
            api_key=api_key,
            timeout=httpx.Timeout(
                connect=CONNECTION_TIMEOUT,  # 5s na połączenie
                read=DEFAULT_TIMEOUT,        # 15s na odczyt
                write=CONNECTION_TIMEOUT,    # 5s na zapis
                pool=CONNECTION_TIMEOUT      # 5s na pool
            ),
            max_retries=DEFAULT_RETRIES,  # 2 próby zamiast 3
            http_client=httpx.Client(
                timeout=httpx.Timeout(
                    connect=CONNECTION_TIMEOUT,
                    read=DEFAULT_TIMEOUT,
                    write=CONNECTION_TIMEOUT,
                    pool=CONNECTION_TIMEOUT
                )
            )
        )

        # Pobierz odpowiedni system prompt w zależności od stylu
        current_system_prompt = get_system_prompt("prompt" if "prompt" in instruction_prompt.lower() else "normal")
        
        # Przygotowanie wiadomości dla modelu
        messages = [
            {"role": "system", "content": current_system_prompt},
            {"role": "user", "content": f"{instruction_prompt}\n\n---\n{text_to_correct}\n---"}
        ]

        # Wysłanie zapytania do API z timeout
        response = None
        
        # Tymczasowe wyłączenie Responses API dla gpt-5-nano - problemy z buildami GitHub Actions
        if "nano" in model.lower() and model.lower().startswith("gpt-5"):
            logger.info(f"Model gpt-5-nano: używam Chat Completions API zamiast Responses API (build compatibility)")
            use_responses_api = False
        else:
            use_responses_api = any(model.lower().startswith(prefix) for prefix in ["gpt-5", "o4", "o3", "o1"])
        
        logger.info(f"Model: {model}, use_responses_api: {use_responses_api}")
        
        try:
            if use_responses_api:
                # Responses API dla nowszych modeli z reasoning controls
                # Pobierz ustawienia z config.ini lub użyj domyślnych
                try:
                    import configparser
                    from utils.config_manager import get_config_path
                    config = configparser.ConfigParser()
                    config.read(get_config_path())
                    reasoning_effort = get_config_value(config, "AI_SETTINGS", "ReasoningEffort", "high")
                    verbosity = get_config_value(config, "AI_SETTINGS", "Verbosity", "medium")
                except:
                    # Fallback values jeśli problem z konfiguracją
                    reasoning_effort = "high"
                    verbosity = "medium"
                
                logger.info(f"OpenAI Responses API: model={model}, reasoning_effort={reasoning_effort}, verbosity={verbosity}")
                
                # Sprawdź czy SDK ma responses API
                if not hasattr(client, 'responses'):
                    logger.warning(f"SDK brak responses API - fallback do chat completions dla {model}")
                    raise AttributeError("No responses API in SDK")
                
                response = client.responses.create(
                    model=model,
                    input=messages,
                    max_output_tokens=2000,
                    reasoning_effort=reasoning_effort,  # Z konfiguracji użytkownika
                    verbosity=verbosity,  # Z konfiguracji użytkownika
                    timeout=DEFAULT_TIMEOUT
                )
                # Responses API: zbuduj tekst
                logger.info(f"Responses API response type: {type(response)}")
                logger.info(f"Response hasattr output: {hasattr(response, 'output')}")
                logger.info(f"Response hasattr content: {hasattr(response, 'content')}")
                
                text_chunks = []
                if hasattr(response, 'output') and response.output:
                    logger.info(f"Processing response.output with {len(response.output)} items")
                    for item in response.output:
                        item_type = getattr(item, 'type', None)
                        logger.debug(f"Output item type: {item_type}")
                        if item_type == 'message' and getattr(item, 'content', None):
                            for part in item.content:
                                part_type = getattr(part, 'type', None)
                                logger.debug(f"Content part type: {part_type}")
                                if part_type == 'output_text':
                                    text = getattr(part, 'text', '') or ''
                                    logger.debug(f"Found output_text: {text[:100]}...")
                                    text_chunks.append(text)
                elif hasattr(response, 'content') and response.content:
                    logger.info(f"Processing response.content with {len(response.content)} parts")
                    # Starsze obiekty mogą mieć content
                    for part in response.content:
                        part_type = getattr(part, 'type', None)
                        logger.debug(f"Content part type: {part_type}")
                        if part_type == 'output_text':
                            text = getattr(part, 'text', '') or ''
                            logger.debug(f"Found output_text: {text[:100]}...")
                            text_chunks.append(text)
                else:
                    logger.warning("No output or content found in Responses API response")
                    logger.info(f"Response attributes: {dir(response)}")
                
                corrected_text = ("".join(text_chunks)).strip()
                logger.info(f"Extracted text length: {len(corrected_text)} chars")
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_completion_tokens=2000,
                    timeout=DEFAULT_TIMEOUT
                )
                # Chat Completions API
                if response.choices and response.choices[0].message:
                    corrected_text = (response.choices[0].message.content or '').strip()
                else:
                    corrected_text = ""
        except (AttributeError, TypeError, Exception) as e:
            # Fallback: SDK nie ma responses API, model nie wspiera parametrów reasoning, lub inne błędy API
            logger.warning(f"Responses API fallback dla {model}: {type(e).__name__}: {e}")
            
            # Próbuj standardowe Chat Completions API
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_completion_tokens=2000,
                    timeout=DEFAULT_TIMEOUT
                )
                corrected_text = (response.choices[0].message.content or '').strip() if (response.choices and response.choices[0].message) else ""
                logger.info(f"Chat Completions API fallback successful, text length: {len(corrected_text)} chars")
            except Exception as fallback_error:
                logger.error(f"Both Responses and Chat Completions API failed for {model}: {fallback_error}")
                # Sprawdź typowe literówki w nazwie modelu
                if "gtp-5" in model.lower():
                    suggested_model = model.replace("gtp-5", "gpt-5")
                    return f"Błąd: Model {model} niedostępny. Czy chodziło o '{suggested_model}'? Popraw nazwę modelu w ustawieniach."
                return f"Błąd: Model {model} niedostępny. Sprawdź nazwę modelu lub spróbuj gpt-4o-mini."

        # Przetworzenie odpowiedzi
        if corrected_text:
            if corrected_text:
                logger.info("Otrzymano poprawną odpowiedź od OpenAI API.")
                # Czyszczenie odpowiedzi
                corrected_text = corrected_text.strip()
                # Usuń wszystkie wystąpienia --- z początku i końca
                while corrected_text.startswith("---"):
                    corrected_text = corrected_text[3:].strip()
                while corrected_text.endswith("---"):
                    corrected_text = corrected_text[:-3].strip()
                
                # Dodatkowe czyszczenie - usuń linie zawierające same ---
                lines = [line for line in corrected_text.splitlines() if line.strip() != "---"]
                corrected_text = "\n".join(lines).strip()
                
                # Usuń puste linie na początku i końcu
                lines = [line for line in corrected_text.splitlines() if line.strip()]
                
                # Usuń pierwszą linię jeśli to nazwa stylu
                style_names = ["normal", "professional", "translate_en", "translate_pl", "change_meaning", "summary"]
                if lines and any(style in lines[0].lower() for style in style_names):
                    lines = lines[1:]
                
                return "\n".join(lines).strip()
            else:
                logger.warning("Otrzymano odpowiedź od OpenAI, ale treść wiadomości jest pusta.") # Logowanie ostrzeżenia
                return "Błąd: Nie otrzymano poprawnej odpowiedzi od OpenAI API (brak treści w wiadomości)."
        else:
            logger.warning("Otrzymano odpowiedź od OpenAI, ale treść jest pusta.")
            return "Błąd: Nie otrzymano poprawnej odpowiedzi od OpenAI API (brak treści w wiadomości)."

    except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        logger.error(f"Timeout OpenAI API: {e}", exc_info=True)
        return f"Błąd: OpenAI API nie odpowiada (timeout {DEFAULT_TIMEOUT}s). Spróbuj ponownie."
    except (HTTPError, TimeoutException, openai.APIConnectionError) as e:
        if handle_api_error(e):
            return "Błąd połączenia z API. Sprawdź komunikat błędu."
        logger.error(f"Błąd połączenia z OpenAI API: {e}", exc_info=True) # Logowanie błędu
        return f"Błąd połączenia z OpenAI API: {e}"
    except openai.RateLimitError as e:
        logger.warning(f"Przekroczono limit zapytań do OpenAI API: {e}") # Logowanie ostrzeżenia
        return f"Błąd OpenAI (limit zapytań): {e}"
    except openai.AuthenticationError as e:
        logger.error(f"Błąd autentykacji OpenAI API (prawdopodobnie zły klucz): {e}", exc_info=True) # Logowanie błędu
        return f"Błąd OpenAI (autentykacja - zły klucz?): {e}"
    except openai.APIStatusError as e:
        logger.error(f"Ogólny błąd statusu OpenAI API: {e} (Status: {e.status_code}, Response: {e.response})", exc_info=True) # Logowanie błędu z dodatkowymi informacjami
        return f"Błąd OpenAI (status API {e.status_code}): {e.response}"
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd podczas komunikacji z OpenAI: {e}", exc_info=True) # Logowanie błędu
        return f"Błąd OpenAI (nieoczekiwany): {e}"


if __name__ == '__main__':
    # Prosty test działania (wymaga ustawienia klucza API i modelu poniżej lub w zmiennych środowiskowych)
    # Pamiętaj, aby zastąpić 'YOUR_OPENAI_API_KEY' i 'YOUR_MODEL' (np. "gpt-3.5-turbo")
    # lub załadować je z pliku konfiguracyjnego.

    # --- Modyfikacja sys.path dla testowania bezpośredniego ---
    # Zakładamy, że ten plik (openai_client.py) jest w PoprawiaczTekstuPy/api_clients/
    # Musimy dodać PoprawiaczTekstuPy do sys.path, aby importy z api_clients zadziałały
    current_script_path = os.path.abspath(__file__)
    # api_clients_dir to .../PoprawiaczTekstuPy/api_clients
    api_clients_dir = os.path.dirname(current_script_path)
    # project_root_dir to .../PoprawiaczTekstuPy
    project_root_dir = os.path.dirname(api_clients_dir)
    
    if project_root_dir not in sys.path:
        sys.path.insert(0, project_root_dir)
    
    # Teraz możemy spróbować importu, który wcześniej zawodził, jeśli był potrzebny
    # from api_clients.base_client import APIConnectionError, APIResponseError # Przykład
    # W tym konkretnym pliku openai_client.py nie używamy niczego z base_client,
    # więc linia 'from .base_client import...' na górze może zostać usunięta lub zakomentowana
    # jeśli nie planujemy jej używać.
    # Dla czystości, jeśli nie jest używana, lepiej ją usunąć.
    # Na potrzeby tego testu, zakładamy, że nie jest potrzebna w tym pliku.

    # --- PRZYKŁAD UŻYCIA --- 
    # Ustaw poniższe zmienne przed uruchomieniem tego bloku testowego
    test_api_key = "YOUR_DEEPSEEK_API_KEY"  # Wstaw swój klucz OpenAI
    test_model = "o4-mini"      # Wstaw model, np. "gpt-3.5-turbo"
    
    if test_api_key == "YOUR_OPENAI_API_KEY" or not test_api_key:
        print("Aby przetestować, ustaw `test_api_key` oraz `test_model` w sekcji if __name__ == '__main__'.")
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
        
        print(f"Wysyłanie zapytania do OpenAI z modelem: {test_model}...")
        result = correct_text_openai(test_api_key, test_model, sample_text, sample_instruction, sample_system_prompt)
        print("--- Wynik z OpenAI ---")
        print(result)
        print("----------------------") 