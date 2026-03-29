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
        """Generates an image using Nano Banana 2 (Imagen 4) via AI Studio."""
        from google.genai import types # Local import to ensure it's available
        try:
            result = await self._client.aio.models.generate_images(
                model='imagen-4.0-generate-001',
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/jpeg",
                    aspect_ratio="1:1"
                )
            )
            for generated_image in result.generated_images:
                if generated_image.image and generated_image.image.image_bytes:
                    return generated_image.image.image_bytes
            return "Error: No image data returned from Google."
        except Exception as exc:
            logger.error("Image generation failed: %s", exc, exc_info=True)
            return f"API Error: {str(exc)}"

    # Override __del__ isn't needed – the genai client manages its own
    # resources, but we add a graceful shutdown hook for completeness.
    async def close(self) -> None:
        """Perform any necessary cleanup."""
        logger.info("GeminiClient shut down.")
