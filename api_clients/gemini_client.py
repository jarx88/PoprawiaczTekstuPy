"""Gemini client streaming built on the official google-genai SDK.

The implementation focuses on a single transport – ``google-genai`` – which is the
library Google now documents for the Gemini API. Streaming is handled through
``client.models.generate_content_stream``; incremental text chunks are forwarded to
our UI callback, and we honor cancellation via ``threading.Event`` so the UI can
interrupt long generations without waiting for the back end to finish.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional
import threading

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from gui.prompts import get_system_prompt
from utils.logger import log_api_error, log_connection_error, logger

ChunkCallback = Callable[[str], None]


@dataclass
class _StreamingState:
    """Tracks incremental text and logs the first emission."""

    aggregated_text: str = ""
    has_emitted: bool = False

    def push(self, text: str, on_chunk: Optional[ChunkCallback]) -> None:
        if not text:
            return
        if not self.has_emitted:
            logger.info("Gemini stream: pierwsza porcja tekstu (%s znaków)", len(text))
            self.has_emitted = True
        self.aggregated_text += text
        if callable(on_chunk):
            try:
                on_chunk(text)
            except Exception:  # pragma: no cover - defensive
                logger.debug("Gemini on_chunk callback raised", exc_info=True)


def _build_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _build_generation_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        candidate_count=1,
        max_output_tokens=3072,
        temperature=0.7,
        top_p=0.9,
        top_k=32,
        thinking_config=types.ThinkingConfig(thinking_budget=0),  # disables extra "thinking" delay on 2.5 models
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ],
    )


def _close_stream(response: object) -> None:
    closer = getattr(response, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:  # pragma: no cover - best effort
            logger.debug("Closing Gemini stream raised", exc_info=True)


def correct_text_gemini(
    api_key: str,
    model: str,
    text_to_correct: str,
    instruction_prompt: str,
    system_prompt: str,
    on_chunk: Optional[ChunkCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Correct text with Gemini using streaming only."""

    style = "prompt" if "prompt" in instruction_prompt.lower() else "normal"
    system_instruction = system_prompt or get_system_prompt(style)

    if not api_key:
        logger.warning("Próba użycia Google Gemini API bez klucza.")
        return "Błąd: Klucz API Google Gemini nie został podany."
    if not model:
        logger.warning("Próba użycia Google Gemini API bez podania modelu.")
        return "Błąd: Model Google Gemini nie został określony."
    if not text_to_correct:
        logger.warning("Próba użycia Google Gemini API bez tekstu do poprawy.")
        return "Błąd: Brak tekstu do poprawy."

    if cancel_event and cancel_event.is_set():
        return "❌ Anulowano"

    logger.info(
        "Wysyłanie zapytania do Google Gemini API (model: %s). Tekst: %s...",
        model,
        text_to_correct[:50],
    )

    client = _build_client(api_key)
    contents = [
        {
            "role": "user",
            "parts": [
                {"text": instruction_prompt},
                {"text": text_to_correct},
            ],
        }
    ]

    state = _StreamingState()

    try:
        stream = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=_build_generation_config(),
            system_instruction=system_instruction,
        )

        last_chunk_text = ""
        for chunk in stream:
            if cancel_event and cancel_event.is_set():
                _close_stream(stream)
                return state.aggregated_text or "❌ Anulowano"

            chunk_text = getattr(chunk, "text", None)
            if not chunk_text:
                # Fallback to parts if text property is empty (older SDK builds).
                parts = getattr(chunk, "candidates", None)
                if parts:
                    try:
                        chunk_text = parts[0].content.parts[0].text  # type: ignore[attr-defined]
                    except Exception:  # pragma: no cover - defensive
                        chunk_text = ""
            if chunk_text:
                last_chunk_text = chunk_text
                state.push(chunk_text, on_chunk)

        final_text = state.aggregated_text or last_chunk_text
        if not final_text:
            logger.warning("Gemini nie zwrócił treści w odpowiedzi.")
            return "Błąd: Gemini nie zwrócił treści w odpowiedzi."
        return final_text.strip()

    except genai_errors.ClientError as err:
        log_api_error("Gemini", err)
        return f"Błąd Gemini (HTTP {getattr(err, 'code', '??')}): {err}"
    except genai_errors.GoogleAPICallError as err:
        log_connection_error("Gemini", err)
        return f"Błąd Gemini (połączenie): {err}"
    except Exception as err:  # pragma: no cover - catch-all for SDK regressions
        log_connection_error("Gemini", err)
        return f"Błąd Gemini (nieoczekiwany): {err}"
