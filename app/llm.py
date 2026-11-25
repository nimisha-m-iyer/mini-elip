"""Thin client for Groq's OpenAI-compatible chat API (open-weight Llama models)."""
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger("llm")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(Exception):
    """A non-retryable LLM failure (bad key, bad model name, bad request)."""


# Retry network errors, timeouts, 429 (rate limit) and 5xx with exponential backoff.
# 4xx errors such as a wrong key or model name are NOT retried: retrying cannot fix them.
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type(httpx.TransportError),
    reraise=True,
)
def _post(payload):
    r = httpx.post(
        GROQ_URL,
        json=payload,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        timeout=httpx.Timeout(connect=10, read=60, write=20, pool=10),
    )
    if r.status_code == 429 or r.status_code >= 500:
        raise httpx.TransportError(f"retryable status {r.status_code}: {r.text[:200]}")
    if r.status_code >= 400:
        raise LLMError(f"Groq returned {r.status_code}: {r.text[:300]}")
    return r.json()


def chat(messages, json_mode=True, temperature=0.0, max_tokens=4000):
    """Send chat messages, return the reply text. json_mode asks for valid JSON output."""
    if not settings.groq_api_key:
        raise LLMError("GROQ_API_KEY is empty. Put your key in .env and recreate the app container.")
    payload = {
        "model": settings.groq_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if "gpt-oss" in settings.groq_model:
        # Reasoning model: keep its thinking short so tokens go to the answer and it stays fast.
        payload["reasoning_effort"] = "low"
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post(payload)
    content = data["choices"][0]["message"].get("content") or ""
    if not content.strip():
        raise LLMError("The model returned an empty reply (it may have run out of tokens).")
    return content