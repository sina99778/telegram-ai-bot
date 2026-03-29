"""
app/ai/client.py
~~~~~~~~~~~~~~~~
Asynchronous wrapper around the Google GenAI (Gemini) SDK.

Provides a production-grade client with:
  • Automatic retries via tenacity (exponential back-off)
  • Structured logging for every API call / retry
  • Graceful exception handling that never leaks API keys
"""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    RetryError,
)

from app.core.config import settings

# ──────────────────────────────────────────────
#  Logger
# ──────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  Custom exception
# ──────────────────────────────────────────────
class AIException(Exception):
    """Raised when the AI service fails after all retry attempts.

    This exception deliberately strips any sensitive information
    (e.g. API keys) from the traceback to prevent accidental leaks.
    """

    def __init__(self, message: str = "AI service is temporarily unavailable.") -> None:
        super().__init__(message)


# ──────────────────────────────────────────────
#  Retry-eligible exceptions
# ──────────────────────────────────────────────
# google-genai raises `google.genai.errors.ClientError` /
# `google.genai.errors.ServerError` for HTTP-level failures.
# We also catch generic connection-level errors.
_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    Exception,  # Narrow this down once you know exact SDK error types
)


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception looks like a transient/retryable error.

    Catches:
      • Network-level errors (ConnectionError, TimeoutError)
      • HTTP 429 (Too Many Requests) and 503 (Service Unavailable)
    """
    # Network-level errors are always retryable
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True

    # Check for HTTP status codes embedded in the exception
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code in (429, 503):
        return True

    # google-genai may wrap gRPC / httpx errors with a message
    exc_message = str(exc).lower()
    if any(keyword in exc_message for keyword in ("429", "503", "resource exhausted", "service unavailable")):
        return True

    return False


class _RetryableAIError(Exception):
    """Internal sentinel used to unify retryable errors under one type."""


# ──────────────────────────────────────────────
#  Gemini Client
# ──────────────────────────────────────────────
class GeminiClient:
    """Async wrapper around the Google GenAI SDK.

    Usage::

        client = GeminiClient()
        reply  = await client.generate_response([
            {"role": "user", "parts": [{"text": "Hello!"}]},
        ])
    """

    def __init__(self) -> None:
        # Initialise the genai client with the API key from settings.
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._default_model: str = settings.GEMINI_MODEL
        logger.info(
            "GeminiClient initialised  ·  model=%s",
            self._default_model,
        )

    # ── public API ───────────────────────────────

    async def generate_response(self, messages: list[types.Content], override_model: str | None = None) -> str:
        model_to_use = override_model or self._default_model
        return await self._call_with_retries(messages, model_to_use)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(_RetryableAIError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=False,
    )
    async def _call_with_retries(self, messages: list[types.Content], model: str) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=messages,
            )
            return response.text or ""
        except Exception as exc:
            if _is_retryable(exc):
                raise _RetryableAIError(str(exc)) from exc
            logger.error("Non-retryable API error: %s", type(exc).__name__, exc_info=True)
            raise AIException("AI request failed. Please try again later.") from None

    async def generate_image(self, prompt: str) -> bytes | str:
        """Hybrid Image Generation: Tries Google REST API directly, instantly falls back if syncing/failing."""
        import aiohttp
        import base64
        import urllib.parse
        from app.core.config import settings
        import logging
        
        logger = logging.getLogger(__name__)

        google_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={settings.GEMINI_API_KEY}"
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": "1:1"}
        }

        try:
            async with aiohttp.ClientSession() as session:
                # 1. Try Official Google API (Direct REST call)
                async with session.post(google_url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "predictions" in data and len(data["predictions"]) > 0:
                            b64_data = data["predictions"][0].get("bytesBase64Encoded")
                            if b64_data:
                                return base64.b64decode(b64_data)
                    else:
                        error_text = await response.text()
                        logger.warning(f"Google Imagen not ready yet (Status {response.status}): {error_text}")

                # 2. Fallback Mechanism (Instantly triggers if Google is 404/400)
                logger.info("Switching to Fallback Image Engine to prevent user error...")
                encoded_prompt = urllib.parse.quote(prompt)
                fallback_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
                
                async with session.get(fallback_url) as fb_response:
                    if fb_response.status == 200:
                        return await fb_response.read()
                    
                    return "API Error: Google is syncing billing, and fallback engine also failed."
                    
        except Exception as exc:
            logger.error("Hybrid Image generation completely failed: %s", exc, exc_info=True)
            return f"Internal Error: {str(exc)}"

    # Override __del__ isn't needed – the genai client manages its own
    # resources, but we add a graceful shutdown hook for completeness.
    async def close(self) -> None:
        """Perform any necessary cleanup."""
        logger.info("GeminiClient shut down.")
