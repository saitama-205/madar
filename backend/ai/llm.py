"""OpenRouter client. Key and model come from environment variables (or the repo's git-ignored .env file).

    OPENROUTER_API_KEY   required for any AI feature; without it every call raises LLMUnavailable (never crashes)
    OPENROUTER_MODEL     optional, default openai/gpt-4o-mini

Callers catch LLMError (LLMUnavailable is a kind of LLMError) and fall back or answer 503 ai_unavailable.
"""
import json
import os
import re
import time
from pathlib import Path

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
TIMEOUT_SECONDS = 20.0
RETRY_DELAYS = (2.0, 5.0)  # seconds to wait before each retry after HTTP 429 (rate limited)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class LLMError(Exception):
    """The AI could not be used (no key, network problem, error status, unreadable answer)."""


class LLMUnavailable(LLMError):
    """No API key is configured."""


def _read_env_file(name: str) -> str | None:
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip("'\"") or None
    except OSError:
        pass
    return None


def _setting(name: str) -> str | None:
    return (os.environ.get(name) or "").strip() or _read_env_file(name)


def get_api_key() -> str | None:
    return _setting("OPENROUTER_API_KEY")


def get_model() -> str:
    return _setting("OPENROUTER_MODEL") or DEFAULT_MODEL


def is_configured() -> bool:
    return get_api_key() is not None


def _send(payload: dict, headers: dict) -> tuple[int, str]:
    """One HTTP call. A separate function so tests can replace it without any network."""
    try:
        r = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as e:
        raise LLMError(f"Could not reach the AI service ({type(e).__name__}).") from e
    return r.status_code, r.text


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int = 400) -> str:
    """Send the messages and return the model's text. Retries on 429. Raises LLMError (never anything else)."""
    key = get_api_key()
    if key is None:
        raise LLMUnavailable("The AI is not configured (OPENROUTER_API_KEY is missing).")
    payload = {"model": get_model(), "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Madar"}

    delays = list(RETRY_DELAYS)
    while True:
        status, text = _send(payload, headers)
        if status == 429 and delays:
            time.sleep(delays.pop(0))
            continue
        break
    if status == 429:
        raise LLMError("The AI service is rate limiting requests. Try again in a minute.")
    if status != 200:
        raise LLMError(f"The AI service answered with status {status}.")  # body not echoed: it may hold request data
    try:
        content = json.loads(text)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMError("The AI service sent an answer in an unexpected format.") from e
    if not isinstance(content, str) or not content.strip():
        raise LLMError("The AI service sent an empty answer.")
    return content.strip()


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply (models sometimes wrap it in ```json fences or add a sentence)."""
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise LLMError("The AI did not answer with the expected format.")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as e:
        raise LLMError("The AI did not answer with the expected format.") from e
    if not isinstance(data, dict):
        raise LLMError("The AI did not answer with the expected format.")
    return data
