"""Gemini client with reliable streaming support.

The Google Gemini ecosystem currently exposes two Python SDKs:
- ``google-genai`` (modern, GA August 2024)
- ``google-generativeai`` (legacy, still widely shipped)

Unfortunately, the legacy SDK suffers from regressions on Windows builds where
``stream=True`` buffers the entire response before yielding any events.  To keep
streaming responsive across all deployment targets, this client prefers the
modern SDK when available and otherwise falls back to a manual SSE transport
built on top of ``httpx``.  As a last resort it uses the legacy synchronous
call.

All transports share the same text‑extraction helpers so that callbacks receive
incremental deltas regardless of the underlying response shape.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
import threading
from typing import Any, Callable, Dict, Iterable, Iterator, Optional

import httpx
from httpx import HTTPError, TimeoutException

# Prefer the modern google-genai SDK.  It may not be present in older builds.
try:  # pragma: no cover - optional dependency
    from google import genai as modern_genai  # type: ignore
    from google.genai import types as modern_types  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    modern_genai = None
    modern_types = None

# Fallback to the legacy SDK if the modern one is unavailable.
try:  # pragma: no cover - optional dependency
    import google.generativeai as legacy_genai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    legacy_genai = None

from gui.prompts import get_system_prompt
from utils.logger import log_api_error, log_connection_error, logger
from .base_client import CONNECTION_TIMEOUT, DEFAULT_TIMEOUT

# Public type used by callers when they pass a streaming callback.
ChunkCallback = Callable[[str], None]

# --- Internal data structures -------------------------------------------------


@dataclass
class _StreamingState:
    """Keeps track of partial text while streaming."""

    aggregated_text: str = ""
    last_snapshot: str = ""

    def emit_delta(self, snapshot: str, on_chunk: Optional[ChunkCallback]) -> None:
        """Derive the delta from a snapshot and dispatch it via ``on_chunk``."""
        if not snapshot or snapshot == self.last_snapshot:
            return

        delta = snapshot
        if self.last_snapshot and snapshot.startswith(self.last_snapshot):
            delta = snapshot[len(self.last_snapshot) :]
        elif self.last_snapshot and self.last_snapshot in snapshot:
            # Snapshot may contain the previous text somewhere in the middle.
            idx = snapshot.rfind(self.last_snapshot)
            tail = snapshot[idx + len(self.last_snapshot) :]
            delta = tail
        elif self.last_snapshot and snapshot in self.last_snapshot:
            # Nothing new.
            delta = ""

        self.last_snapshot = snapshot

        if not delta:
            return

        first_chunk = not self.aggregated_text
        self.aggregated_text += delta

        if first_chunk:
            logger.info("Gemini stream: pierwsza porcja tekstu (%s znaków)", len(delta))

        if callable(on_chunk):
            try:
                on_chunk(delta)
            except Exception:  # pragma: no cover - defensive logging
                logger.debug("Gemini on_chunk callback raised", exc_info=True)


# --- Helpers shared by every transport ---------------------------------------


def _iter_text_from_parts(parts: Optional[Iterable[Any]]) -> Iterator[str]:
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
        if isinstance(text, str) and text:
            yield text


def _extract_text(candidate: Any) -> str:
    if candidate is None:
        return ""

    for attr in ("text", "output_text"):
        value = getattr(candidate, attr, None)
        if isinstance(value, str) and value:
            return value

    candidates = getattr(candidate, "candidates", None)
    collected: list[str] = []
    if candidates:
        for cand in candidates:
            content = getattr(cand, "content", None) or getattr(cand, "contents", None)
            parts = getattr(content, "parts", None)
            if parts is None and isinstance(content, (list, tuple)):
                parts = content
            collected.extend(_iter_text_from_parts(parts))
    if collected:
        return "".join(collected)

    for attr in ("parts", "content", "contents"):
        parts = getattr(candidate, attr, None)
        if parts:
            text_parts = list(_iter_text_from_parts(parts))
            if text_parts:
                return "".join(text_parts)

    delta = getattr(candidate, "delta", None)
    if delta:
        parts = getattr(delta, "parts", None)
        if parts:
            text_parts = list(_iter_text_from_parts(parts))
            if text_parts:
                return "".join(text_parts)

    return ""


def _extract_text_from_dict(data: Dict[str, Any]) -> str:
    if not data:
        return ""

    candidates = data.get("candidates") or []
    collected: list[str] = []
    for cand in candidates:
        content = cand.get("content") or {}
        parts = content.get("parts") or []
        collected.extend(_iter_text_from_parts(parts))
    if collected:
        return "".join(collected)

    if "text" in data and isinstance(data["text"], str):
        return data["text"]

    return ""


def _http_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=CONNECTION_TIMEOUT,
        read=DEFAULT_TIMEOUT,
        write=CONNECTION_TIMEOUT,
        pool=CONNECTION_TIMEOUT,
    )


def _generation_config() -> Dict[str, Any]:
    return {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 32,
        "candidate_count": 1,
        "max_output_tokens": 3072,
        "response_mime_type": "text/plain",
    }


def _generation_config_api() -> Dict[str, Any]:
    cfg = _generation_config()
    return {
        "temperature": cfg["temperature"],
        "topP": cfg["top_p"],
        "topK": cfg["top_k"],
        "candidateCount": cfg["candidate_count"],
        "maxOutputTokens": cfg["max_output_tokens"],
        "responseMimeType": cfg["response_mime_type"],
    }


def _safety_settings() -> list[Dict[str, str]]:
    return [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]


# --- Transports ---------------------------------------------------------------


def _stream_modern_sdk(
    api_key: str,
    model: str,
    contents: list[Dict[str, Any]],
    system_instruction: str,
    on_chunk: Optional[ChunkCallback],
    cancel_event: Optional[threading.Event],
) -> tuple[str, Any]:
    if modern_genai is None:
        raise RuntimeError("google-genai SDK not available")

    client = modern_genai.Client(api_key=api_key)
    generation_conf = _generation_config()
    kwargs: Dict[str, Any] = {
        "model": model,
        "contents": contents,
        "safety_settings": _safety_settings(),
        "system_instruction": system_instruction,
    }
    if modern_types is not None:
        kwargs["config"] = modern_types.GenerateContentConfig(**generation_conf)
    else:
        kwargs["generation_config"] = generation_conf

    state = _StreamingState()
    last_event: Any = None

    stream = client.models.generate_content_stream(**kwargs)
    for event in stream:
        if cancel_event and cancel_event.is_set():
            break
        last_event = event
        snapshot = _extract_text(event)
        state.emit_delta(snapshot, on_chunk)

    final_response = getattr(stream, "response", None) or last_event
    final_text = state.aggregated_text or _extract_text(final_response)
    return final_text, final_response


def _stream_legacy_sdk(
    api_key: str,
    model: str,
    contents: list[Dict[str, Any]],
    system_instruction: str,
    on_chunk: Optional[ChunkCallback],
    cancel_event: Optional[threading.Event],
) -> tuple[str, Any]:
    if legacy_genai is None:
        raise RuntimeError("google-generativeai SDK not available")

    legacy_genai.configure(api_key=api_key)
    state = _StreamingState()

    gemini_model = legacy_genai.GenerativeModel(
        model_name=model,
        generation_config=_generation_config(),
        safety_settings=_safety_settings(),
        system_instruction=system_instruction,
    )

    stream = gemini_model.generate_content(
        contents,
        stream=True,
        request_options={"timeout": DEFAULT_TIMEOUT},
    )

    last_event: Any = None
    for event in stream:
        if cancel_event and cancel_event.is_set():
            break
        last_event = event
        snapshot = _extract_text(event)
        state.emit_delta(snapshot, on_chunk)

    response = None
    if hasattr(stream, "get_final_response"):
        try:
            response = stream.get_final_response()
        except Exception:  # pragma: no cover - defensive
            response = None
    if response is None:
        response = getattr(stream, "response", None) or last_event

    final_text = state.aggregated_text or _extract_text(response)
    return final_text, response


def _stream_via_http(
    api_key: str,
    model: str,
    contents: list[Dict[str, Any]],
    system_instruction: str,
    on_chunk: Optional[ChunkCallback],
    cancel_event: Optional[threading.Event],
) -> tuple[str, Dict[str, Any]]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "x-goog-api-key": api_key,
    }
    payload = {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": system_instruction}],
        },
        "contents": contents,
        "safetySettings": _safety_settings(),
        "generationConfig": _generation_config_api(),
    }

    state = _StreamingState()
    last_chunk: Dict[str, Any] = {}

    with httpx.stream(
        "POST",
        url,
        headers=headers,
        params={"key": api_key},
        timeout=_http_timeout(),
        json=payload,
    ) as response:
        response.raise_for_status()

        for line in response.iter_lines():
            if cancel_event and cancel_event.is_set():
                break
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    logger.debug("Gemini SSE chunk JSON decode failed: %s", data)
                    continue
                last_chunk = chunk
                snapshot = _extract_text_from_dict(chunk)
                state.emit_delta(snapshot, on_chunk)

    final_text = state.aggregated_text or _extract_text_from_dict(last_chunk)
    return final_text, last_chunk


def _call_legacy_sync(
    api_key: str,
    model: str,
    contents: list[Dict[str, Any]],
    system_instruction: str,
    cancel_event: Optional[threading.Event],
) -> str:
    if cancel_event and cancel_event.is_set():
        return ""
    if legacy_genai is None:
        raise RuntimeError("google-generativeai SDK not available")

    legacy_genai.configure(api_key=api_key)
    gemini_model = legacy_genai.GenerativeModel(
        model_name=model,
        generation_config=_generation_config(),
        safety_settings=_safety_settings(),
        system_instruction=system_instruction,
    )

    response = gemini_model.generate_content(
        contents,
        request_options={"timeout": DEFAULT_TIMEOUT},
    )
    extracted = _extract_text(response)
    return extracted.strip()


def _call_http_sync(
    api_key: str,
    model: str,
    contents: list[Dict[str, Any]],
    system_instruction: str,
    cancel_event: Optional[threading.Event],
) -> str:
    if cancel_event and cancel_event.is_set():
        return ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    payload = {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": system_instruction}],
        },
        "contents": contents,
        "safetySettings": _safety_settings(),
        "generationConfig": _generation_config_api(),
    }

    with httpx.Client(timeout=_http_timeout()) as client:
        response = client.post(url, headers=headers, params={"key": api_key}, json=payload)
        response.raise_for_status()
        data = response.json()
        text = _extract_text_from_dict(data)
        return text.strip()


# --- Public entry point -------------------------------------------------------


def correct_text_gemini(
    api_key: str,
    model: str,
    text_to_correct: str,
    instruction_prompt: str,
    system_prompt: str,
    on_chunk: Optional[ChunkCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Correct text using Google Gemini with best-effort streaming."""

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

    contents = [
        {
            "role": "user",
            "parts": [
                {"text": instruction_prompt},
                {"text": text_to_correct},
            ],
        }
    ]

    errors: list[str] = []

    def _cancelled() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    try:
        final_text, _ = _stream_modern_sdk(api_key, model, contents, system_instruction, on_chunk, cancel_event)
        if final_text:
            if cancel_event and cancel_event.is_set():
                return final_text or "❌ Anulowano"
            return final_text
    except Exception as modern_err:  # pragma: no cover - fallbacks are expected
        errors.append(f"modern SDK: {modern_err}")

    if _cancelled():
        return "❌ Anulowano"

    try:
        final_text, _ = _stream_legacy_sdk(api_key, model, contents, system_instruction, on_chunk, cancel_event)
        if final_text:
            if cancel_event and cancel_event.is_set():
                return final_text or "❌ Anulowano"
            return final_text
    except Exception as legacy_err:  # pragma: no cover
        errors.append(f"legacy SDK: {legacy_err}")

    if _cancelled():
        return "❌ Anulowano"

    try:
        final_text, _ = _stream_via_http(api_key, model, contents, system_instruction, on_chunk, cancel_event)
        if final_text:
            if cancel_event and cancel_event.is_set():
                return final_text or "❌ Anulowano"
            return final_text
    except Exception as http_stream_err:  # pragma: no cover
        errors.append(f"stream SSE: {http_stream_err}")

    if _cancelled():
        return "❌ Anulowano"

    try:
        if legacy_genai is not None:
            final_text = _call_legacy_sync(api_key, model, contents, system_instruction, cancel_event)
            if final_text:
                if cancel_event and cancel_event.is_set():
                    return final_text or "❌ Anulowano"
                return final_text
    except Exception as legacy_sync_err:  # pragma: no cover
        errors.append(f"legacy sync: {legacy_sync_err}")

    if _cancelled():
        return "❌ Anulowano"

    try:
        final_text = _call_http_sync(api_key, model, contents, system_instruction, cancel_event)
        if final_text:
            if cancel_event and cancel_event.is_set():
                return final_text or "❌ Anulowano"
            return final_text
    except Exception as http_sync_err:  # pragma: no cover
        errors.append(f"http sync: {http_sync_err}")

    aggregated_error = "; ".join(errors) if errors else "brak danych"
    log_api_error("Gemini", f"Nie udało się uzyskać odpowiedzi Gemini ({aggregated_error})")
    return "Błąd: Nie otrzymano tekstu w odpowiedzi od Gemini API."


if __name__ == "__main__":  # pragma: no cover - manual smoke test helper
    import os

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("⚠️  Ustaw zmienną środowiskową GEMINI_API_KEY aby wykonać test.")
    else:
        sample_instruction = "Popraw następujący tekst, zachowując jego formatowanie."
        sample_text = "To jest tekst z błendem ortograficznym."
        result = correct_text_gemini(
            api_key,
            "gemini-2.5-flash",
            sample_text,
            sample_instruction,
            system_prompt="",
            on_chunk=lambda chunk: print(f"[chunk] {chunk!r}"),
        )
        print("\nFinal result:\n", result)
