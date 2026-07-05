"""Groq client wrapper: JSON-mode calls with per-model fallback, throttle, and retry.

Free-tier reality: 30 req/min and ~1000 req/day PER MODEL. Splitting roles (scoring vs
writing vs checking) across different models multiplies effective capacity. A primary model
hitting its daily cap or rate limit transparently falls back to the configured fallback.
"""
from __future__ import annotations

import json
import time
from typing import Any

from util import env, get_logger

log = get_logger("llm")

_THROTTLE_S = 2.0
_MAX_RETRIES = 2
_last_call_at = 0.0
_MOCK = None  # optional callable(system, user, model, fallback_model, temperature) -> dict


def configure(throttle_s: float, max_retries: int) -> None:
    global _THROTTLE_S, _MAX_RETRIES
    _THROTTLE_S = throttle_s
    _MAX_RETRIES = max_retries


def set_mock(fn) -> None:
    """Route all call_json calls through fn instead of Groq (used by --mock-llm)."""
    global _MOCK
    _MOCK = fn


def _client():
    from groq import Groq

    return Groq(api_key=env("GROQ_API_KEY", required=True))


def _throttle() -> None:
    global _last_call_at
    wait = _THROTTLE_S - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def _extract_json(content: str) -> dict[str, Any]:
    """Parse a JSON object from the model output, tolerating stray prose or code fences."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1].lstrip("json").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise


def call_json(
    system: str, user: str, model: str, fallback_model: str | None = None, temperature: float = 0.4
) -> dict[str, Any]:
    """Return a parsed JSON dict. Tries model, then fallback_model, each with retries."""
    if _MOCK is not None:
        return _MOCK(system, user, model, fallback_model, temperature)
    models = [model] + ([fallback_model] if fallback_model else [])
    last_err: Exception | None = None
    client = _client()

    for m in models:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                _throttle()
                resp = client.chat.completions.create(
                    model=m,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                return _extract_json(resp.choices[0].message.content)
            except Exception as e:  # noqa: BLE001 — Groq raises several error types; treat uniformly
                last_err = e
                msg = str(e).lower()
                # Rate/quota errors: stop retrying this model, move to fallback immediately.
                if "rate" in msg or "quota" in msg or "429" in msg:
                    log.warning("model %s rate/quota limited, switching", m)
                    break
                log.warning("model %s attempt %d failed: %s", m, attempt + 1, e)
                time.sleep(2 ** attempt)
    raise RuntimeError(f"all models failed; last error: {last_err}")
