# from .base_client import APIConnectionError, APIResponseError, DEFAULT_TIMEOUT # Zakomentowano - nieużywane przy bezpośrednim uruchomieniu
# import time # Usunięto - nieużywane
import google.generativeai as genai
import os
import sys
import httpx
from httpx import HTTPError, TimeoutException
from utils.logger import log_api_error, log_connection_error, log_timeout_error, logger
# PyQt6 removed - using CustomTkinter GUI now
from gui.prompts import get_system_prompt
from .base_client import (
    DEFAULT_TIMEOUT,
    QUICK_TIMEOUT,
    CONNECTION_TIMEOUT,
    DEFAULT_RETRIES,
    APITimeoutError,
)
import threading

def show_connection_error():
    """Log connection error - GUI now handled by main application"""
    logger.error("Connection error - cannot connect to API server")
    logger.error("Possible causes: 1) No internet 2) Firewall blocking 3) API server down")

def handle_api_error(e):
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
        logger.error(f"Błąd połączenia: {str(e)}")
        show_connection_error()
        return True
    return False

def correct_text_gemini(api_key, model, text_to_correct, instruction_prompt, system_prompt, on_chunk=None):
    """Poprawia tekst używając Google Gemini API."""
    # Określenie stylu na podstawie zawartości instruction_prompt
    style = "prompt" if "prompt" in instruction_prompt.lower() else "normal"
    system_instruction = get_system_prompt(style)
    if system_prompt:
        system_instruction = system_prompt
    if not api_key:
        logger.warning("Próba użycia Google Gemini API bez klucza.") # Logowanie ostrzeżenia
        return "Błąd: Klucz API Google Gemini nie został podany."
    if not model:
        logger.warning("Próba użycia Google Gemini API bez podania modelu.") # Logowanie ostrzeżenia
        return "Błąd: Model Google Gemini nie został określony."
    if not text_to_correct:
        logger.warning("Próba użycia Google Gemini API bez tekstu do poprawy.") # Logowanie ostrzeżenia
        return "Błąd: Brak tekstu do poprawy."

    logger.info(f"Wysyłanie zapytania do Google Gemini API (model: {model}). Tekst: {text_to_correct[:50]}...") # Logowanie rozpoczęcia zapytania

    try:
        # Konfiguracja klienta z timeoutem
        genai.configure(api_key=api_key)
        
        # Konfiguracja modelu z krótszym timeoutem
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 32,
            "candidate_count": 1,
            "max_output_tokens": 3072,
            "response_mime_type": "text/plain",
        }
        
        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
            }
        ]
        
        user_parts = [
            {"text": instruction_prompt},
            {"text": text_to_correct},
        ]
        contents = [
            {
                "role": "user",
                "parts": user_parts,
            }
        ]

        # Check if GenerativeModel is available (version compatibility)
        try:
            gemini_model = genai.GenerativeModel(
                model_name=model,
                generation_config=generation_config,
                safety_settings=safety_settings,
                system_instruction=system_instruction,
            )
        except AttributeError as e:
            logger.error(f"Gemini API GenerativeModel not available: {e}")
            return f"Błąd: Gemini API niekompatybilna wersja. Zaktualizuj google-generativeai: pip install google-generativeai --upgrade"
        except Exception as e:
            logger.error(f"Gemini API model creation failed: {e}")
            return f"Błąd: Nie można utworzyć modelu Gemini: {e}"

        try:
            token_info = gemini_model.count_tokens(contents)
            total_tokens = getattr(token_info, "total_tokens", None)
            input_tokens = getattr(token_info, "input_tokens", None)
            logger.debug(
                "Gemini token estimate -> total: %s, input: %s",
                total_tokens,
                input_tokens,
            )
        except Exception as token_error:
            logger.debug(f"Gemini count_tokens failed: {token_error}")

        request_options = {"timeout": DEFAULT_TIMEOUT}

        def extract_text(resp):
            try:
                if getattr(resp, 'text', None):
                    return resp.text
            except Exception:
                pass
            try:
                candidates = getattr(resp, 'candidates', []) or []
                texts = []
                for cand in candidates:
                    content = getattr(cand, 'content', None)
                    if not content:
                        continue
                    parts = getattr(content, 'parts', []) or []
                    for part in parts:
                        t = getattr(part, 'text', None)
                        if t:
                            texts.append(t)
                return "\n".join(texts)
            except Exception:
                return ""

        # Streaming jeśli dostępny i podano callback on_chunk
        response = None
        if callable(on_chunk) and hasattr(gemini_model, 'generate_content'):
            try:
                collected = []
                stream = gemini_model.generate_content(
                    contents,
                    stream=True,
                    request_options=request_options,
                )

                for event in stream:
                    try:
                        text_chunk = extract_text(event) or getattr(event, 'text', '')
                    except Exception:
                        text_chunk = ''
                    if not text_chunk:
                        continue
                    collected.append(text_chunk)
                    try:
                        on_chunk(text_chunk)
                    except Exception:
                        pass

                response = stream
                if hasattr(stream, 'resolve'):
                    try:
                        response = stream.resolve()
                    except Exception:
                        response = stream
                if response is None and collected:
                    class _StreamResponse:
                        def __init__(self, text):
                            self.text = text

                    response = _StreamResponse("".join(collected))
            except Exception as e:
                logger.warning(f"Gemini streaming failed, fallback to non-streaming: {e}")

        if response is None:
            # WAŻNE: Gemini SDK nie obsługuje timeout bezpośrednio, więc używamy wątku
            result = [None]
            exception = [None]
            
            def make_request():
                try:
                    result[0] = gemini_model.generate_content(
                        contents,
                        request_options=request_options,
                    )
                except AttributeError as e:
                    # Handle Gemini API version compatibility issues
                    if "GenerativeModel" in str(e) or "generate_content" in str(e):
                        logger.error(f"Gemini API version compatibility issue: {e}")
                        exception[0] = Exception(f"Gemini API niekompatybilna wersja: {e}")
                    else:
                        exception[0] = e
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=make_request)
            thread.daemon = True
            thread.start()
            thread.join(timeout=DEFAULT_TIMEOUT + 5)
            
            if thread.is_alive():
                logger.error(f"Timeout Gemini API: przekroczono {DEFAULT_TIMEOUT + 5}s")
                return f"Błąd: Gemini API nie odpowiada (timeout {DEFAULT_TIMEOUT + 5}s). Spróbuj ponownie."
            
            if exception[0]:
                raise exception[0]
            
            response = result[0]

        # Spróbuj bezpiecznie zbudować tekst z candidates -> content -> parts -> text
        extracted = (extract_text(response) or '').strip()
        if extracted:
            logger.info("Otrzymano poprawną odpowiedź od Google Gemini API.")
            return extracted
        elif response.prompt_feedback and response.prompt_feedback.block_reason:
            block_reason = response.prompt_feedback.block_reason
            block_message = f"Prompt zablokowany przez Gemini. Powód: {block_reason}"
            if response.prompt_feedback.safety_ratings:
                block_message += f"\nOceny bezpieczeństwa: {response.prompt_feedback.safety_ratings}"
            logger.warning(block_message) # Logowanie ostrzeżenia dla blokady promptu
            return f"Błąd Gemini: {block_message}"
        else:
            try:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                # 2 == SAFETY lub inny nie-STOP: podaj klarowny komunikat
                if str(finish_reason) != "STOP":
                    error_msg = f"Gemini API zakończyło generowanie z powodem: {finish_reason}. Treść została wycięta przez model."
                    logger.warning(error_msg)
                    return f"Błąd Gemini: {error_msg}"
            except (AttributeError, IndexError):
                pass
            error_msg = "Nie otrzymano tekstu w odpowiedzi od Gemini API lub odpowiedź jest niekompletna."
            log_api_error("Gemini", error_msg, response)
            return f"Błąd: {error_msg}"

    except (HTTPError, TimeoutException) as e:
        if handle_api_error(e):
            return "Błąd połączenia z API. Sprawdź komunikat błędu."
        log_api_error("Gemini", e, getattr(e, 'response', None))
        return f"Błąd Gemini (HTTP): {str(e)}"
    
    except Exception as e:
        # Ogólna obsługa innych błędów
        log_connection_error("Gemini", e) # Możemy użyć log_connection_error lub log_api_error
        return f"Błąd Gemini (nieoczekiwany): {str(e)}"

if __name__ == '__main__':
    # --- Modyfikacja sys.path dla testowania bezpośredniego ---
    current_script_path = os.path.abspath(__file__)
    api_clients_dir = os.path.dirname(current_script_path)
    project_root_dir = os.path.dirname(api_clients_dir)
    if project_root_dir not in sys.path:
        sys.path.insert(0, project_root_dir)

    # --- PRZYKŁAD UŻYCIA ---
    test_api_key = "YOUR_GOOGLE_AI_STUDIO_API_KEY"  # Wstaw swój klucz Google AI Studio
    # Przykładowe modele: "gemini-pro", "gemini-1.0-pro", "gemini-1.5-flash-latest"
    test_model = "gemini-2.5-flash-preview-04-17" # Wybierz model

    if test_api_key == "YOUR_GOOGLE_AI_STUDIO_API_KEY" or not test_api_key:
        logger.info("Aby przetestować, ustaw `test_api_key` (Google AI Studio) oraz `test_model` w sekcji if __name__ == '__main__'.") # Używamy loggera
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

        logger.info(f"Wysyłanie zapytania do Google Gemini z modelem: {test_model}...") # Używamy loggera
        result = correct_text_gemini(test_api_key, test_model, sample_text, sample_instruction, sample_system_prompt)
        logger.info("--- Wynik z Google Gemini ---") # Używamy loggera
        logger.info(result) # Używamy loggera
        logger.info("---------------------------") # Używamy loggera 
