# from .base_client import APIConnectionError, APIResponseError, DEFAULT_TIMEOUT # Zakomentowano - nieużywane przy bezpośrednim uruchomieniu
# import time # Usunięto - nieużywane
import os
import sys
import threading
from typing import Iterable, Optional

import httpx
from httpx import HTTPError, TimeoutException

try:  # Prefer the modern google-genai SDK when available
    from google import genai as modern_genai  # type: ignore
    from google.genai import types as modern_types  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    modern_genai = None
    modern_types = None

try:  # Fallback to legacy google-generativeai SDK
    import google.generativeai as legacy_genai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    legacy_genai = None

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


def _iter_text_from_parts(parts: Optional[Iterable]) -> Iterable[str]:
    """Yield text fragments from Gemini SDK part objects or dicts."""
    if not parts:
        return
    for part in parts:
        if part is None:
            continue
        if isinstance(part, str):
            text = part.strip()
            if text:
                yield text
            continue
        if isinstance(part, dict):
            text = part.get("text")
            if text:
                yield text
            continue
        text = getattr(part, "text", None)
        if text:
            yield text


def _extract_text_from_response(resp) -> str:
    """Safely extract textual content from Gemini SDK responses (streamed or final)."""
    if resp is None:
        return ""

    for attr in ("text", "output_text"):
        try:
            value = getattr(resp, attr, None)
            if isinstance(value, str) and value:
                return value
        except Exception:
            continue

    try:
        candidates = getattr(resp, "candidates", None)
    except Exception:
        candidates = None

    collected: list[str] = []
    if candidates:
        for cand in candidates or []:
            content = getattr(cand, "content", None)
            if content is None:
                continue
            parts = getattr(content, "parts", None)
            if parts is None and isinstance(content, (list, tuple)):
                parts = content
            collected.extend(_iter_text_from_parts(parts))
    if collected:
        return "".join(collected)

    for attr in ("parts", "content"):
        parts = getattr(resp, attr, None)
        if parts:
            text_parts = list(_iter_text_from_parts(parts))
            if text_parts:
                return "".join(text_parts)

    delta = getattr(resp, "delta", None)
    if delta is not None:
        delta_parts = getattr(delta, "parts", None)
        if delta_parts:
            text_parts = list(_iter_text_from_parts(delta_parts))
            if text_parts:
                return "".join(text_parts)

    return ""


def _consume_stream(stream, on_chunk):
    """Consume a Gemini streaming iterator, emitting incremental chunks via callback."""
    aggregated = ""
    collected_segments: list[str] = []
    last_event = None

    for event in stream:
        last_event = event
        try:
            snapshot = _extract_text_from_response(event)
        except Exception as extract_error:  # pragma: no cover - defensive
            logger.debug("Gemini stream extract error: %s", extract_error)
            snapshot = ""

        if not snapshot:
            continue

        delta = snapshot
        if aggregated:
            if snapshot.startswith(aggregated):
                delta = snapshot[len(aggregated):]
            elif aggregated in snapshot:
                # Snapshot zawiera poprzedni fragment w środku – wytnij powtórki
                delta = snapshot.replace(aggregated, "", 1)
        if not delta:
            continue

        aggregated += delta
        collected_segments.append(delta)
        if callable(on_chunk):
            try:
                logger.debug("Gemini stream chunk (%s chars)", len(delta))
                on_chunk(delta)
            except Exception:
                logger.debug("Gemini on_chunk callback raised", exc_info=True)

    combined_text = "".join(collected_segments)
    return combined_text, last_event


def correct_text_gemini(api_key, model, text_to_correct, instruction_prompt, system_prompt, on_chunk=None):
    """Poprawia tekst używając Google Gemini API z obsługą streamingu (modern/legacy SDK)."""
    style = "prompt" if "prompt" in instruction_prompt.lower() else "normal"
    system_instruction = get_system_prompt(style)
    if system_prompt:
        system_instruction = system_prompt

    if not api_key:
        logger.warning("Próba użycia Google Gemini API bez klucza.")
        return "Błąd: Klucz API Google Gemini nie został podany."
    if not model:
        logger.warning("Próba użycia Google Gemini API bez podania modelu.")
        return "Błąd: Model Google Gemini nie został określony."
    if not text_to_correct:
        logger.warning("Próba użycia Google Gemini API bez tekstu do poprawy.")
        return "Błąd: Brak tekstu do poprawy."

    logger.info("Wysyłanie zapytania do Google Gemini API (model: %s). Tekst: %s...", model, text_to_correct[:50])

    try:
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 32,
            "candidate_count": 1,
            "max_output_tokens": 3072,
            "response_mime_type": "text/plain",
        }
        modern_generation_config = {k: v for k, v in generation_config.items() if k != "candidate_count"}

        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": instruction_prompt},
                    {"text": text_to_correct},
                ],
            }
        ]

        request_options = {"timeout": DEFAULT_TIMEOUT}
        response = None

        if modern_genai is not None:
            try:
                modern_client = modern_genai.Client(api_key=api_key)
                modern_kwargs = dict(
                    model=model,
                    contents=contents,
                    safety_settings=safety_settings,
                    system_instruction=system_instruction,
                )
                if modern_types is not None:
                    modern_kwargs["config"] = modern_types.GenerateContentConfig(**modern_generation_config)
                else:
                    modern_kwargs["generation_config"] = modern_generation_config

                if callable(on_chunk):
                    try:
                        stream = modern_client.models.generate_content_stream(**modern_kwargs)
                        streamed_text, last_event = _consume_stream(stream, on_chunk)
                        response = getattr(stream, "response", None) or last_event
                        if streamed_text:
                            logger.info("Otrzymano strumieniową odpowiedź od Google Gemini API (modern SDK).")
                            return streamed_text
                    except Exception as modern_stream_error:
                        logger.warning(
                            "Gemini (modern SDK) streaming failed, fallback do legacy path: %s",
                            modern_stream_error,
                        )

                if response is None:
                    response = modern_client.models.generate_content(**modern_kwargs)
                    extracted_modern = (_extract_text_from_response(response) or "").strip()
                    if extracted_modern:
                        logger.info("Otrzymano odpowiedź od Google Gemini API (modern SDK).")
                        return extracted_modern
            except Exception as modern_error:
                logger.warning(
                    "Nowe SDK google-genai zgłosiło błąd, przełączam na legacy: %s",
                    modern_error,
                )
                response = None

        if legacy_genai is None:
            logger.error("Brak bibliotek google-genai oraz google-generativeai - Gemini nieobsługiwane.")
            return (
                "Błąd: Brak biblioteki Google Gemini SDK. Zainstaluj pakiet google-genai lub google-generativeai."
            )

        try:
            legacy_genai.configure(api_key=api_key)
            gemini_model = legacy_genai.GenerativeModel(
                model_name=model,
                generation_config=generation_config,
                safety_settings=safety_settings,
                system_instruction=system_instruction,
            )
        except AttributeError as e:
            logger.error("Gemini API GenerativeModel not available: %s", e)
            return (
                "Błąd: Gemini API niekompatybilna wersja. Zaktualizuj pakiet google-generativeai (pip install google-generativeai --upgrade)."
            )
        except Exception as e:
            logger.error("Gemini API model creation failed: %s", e)
            return f"Błąd: Nie można utworzyć modelu Gemini: {e}"

        try:
            token_info = gemini_model.count_tokens(contents)
            total_tokens = getattr(token_info, "total_tokens", None)
            input_tokens = getattr(token_info, "input_tokens", None)
            logger.debug("Gemini token estimate -> total: %s, input: %s", total_tokens, input_tokens)
        except Exception as token_error:
            logger.debug("Gemini count_tokens failed: %s", token_error)

        if callable(on_chunk):
            try:
                stream = gemini_model.generate_content(
                    contents,
                    stream=True,
                    request_options=request_options,
                )
                streamed_text, last_event = _consume_stream(stream, on_chunk)
                response = None
                if hasattr(stream, "get_final_response"):
                    try:
                        response = stream.get_final_response()
                    except Exception:
                        response = None
                if response is None:
                    response = getattr(stream, "response", None)
                if response is None:
                    response = last_event
                if streamed_text:
                    logger.info("Otrzymano poprawną strumieniową odpowiedź od Google Gemini API.")
                    return streamed_text
            except Exception as legacy_stream_error:
                logger.warning(
                    "Gemini streaming failed, fallback do trybu synchronicznego: %s",
                    legacy_stream_error,
                )
                response = None

        if response is None:
            result = [None]
            exception = [None]

            def make_request():
                try:
                    result[0] = gemini_model.generate_content(
                        contents,
                        request_options=request_options,
                    )
                except AttributeError as e:
                    if "GenerativeModel" in str(e) or "generate_content" in str(e):
                        logger.error("Gemini API version compatibility issue: %s", e)
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
                logger.error("Timeout Gemini API: przekroczono %ss", DEFAULT_TIMEOUT + 5)
                return f"Błąd: Gemini API nie odpowiada (timeout {DEFAULT_TIMEOUT + 5}s). Spróbuj ponownie."

            if exception[0]:
                raise exception[0]

            response = result[0]

        extracted = (_extract_text_from_response(response) or "").strip()
        if extracted:
            logger.info("Otrzymano poprawną odpowiedź od Google Gemini API.")
            return extracted

        if response and getattr(response, "prompt_feedback", None) and response.prompt_feedback.block_reason:
            block_reason = response.prompt_feedback.block_reason
            block_message = f"Prompt zablokowany przez Gemini. Powód: {block_reason}"
            if response.prompt_feedback.safety_ratings:
                block_message += f"\nOceny bezpieczeństwa: {response.prompt_feedback.safety_ratings}"
            logger.warning(block_message)
            return f"Błąd Gemini: {block_message}"

        if response:
            try:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                if str(finish_reason) != "STOP":
                    error_msg = (
                        f"Gemini API zakończyło generowanie z powodem: {finish_reason}. Treść została wycięta przez model."
                    )
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
        log_connection_error("Gemini", e)
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
