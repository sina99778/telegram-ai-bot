import asyncio
import logging
from typing import List, Dict, Optional, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
)

from app.services.ai.provider import BaseAIProvider, AIMessage, AIResponse
from google import genai
from google.genai import types
from app.core.config import settings

logger = logging.getLogger(__name__)


class SafetyBlockedError(Exception):
    """Raised when Gemini blocks the request/response due to safety filters."""

    def __init__(self, category: str = "unknown", message: str = "Content blocked by safety filters."):
        self.category = category
        super().__init__(message)


class QuotaExhaustedError(Exception):
    """Raised when Gemini rejects with 429 RESOURCE_EXHAUSTED — the project's
    prepay credits/quota are depleted (a billing issue, not a transient one).
    Not retried, and surfaced to the user as a clean 'temporarily unavailable'."""


def _is_quota_error(exc: BaseException) -> bool:
    text = str(exc).upper()
    return "RESOURCE_EXHAUSTED" in text or "429" in text or "QUOTA" in text or "CREDITS ARE DEPLETED" in text


# Tenacity exception predicate: retry only on transient/recoverable errors.
# Never retry on safety blocks (user content issue, not transient), nor on
# cancellation / system-exit style exceptions (those should propagate fast).
_NON_RETRY_TYPES: tuple[type[BaseException], ...] = (
    SafetyBlockedError,
    QuotaExhaustedError,
    asyncio.CancelledError,
    KeyboardInterrupt,
    SystemExit,
    MemoryError,
)


def _should_retry_gemini_error(exc: BaseException) -> bool:
    if isinstance(exc, _NON_RETRY_TYPES):
        return False
    # Quota/billing depletion is persistent — retrying just wastes time.
    if _is_quota_error(exc):
        return False
    # asyncio.TimeoutError, ConnectionError, OSError, google.genai errors → retry
    return isinstance(exc, Exception)


# ── Default safety settings ──
# We rely on the model's default thresholds (typically BLOCK_MEDIUM_AND_ABOVE)
# since free-tier API keys will throw HTTP 400 Bad Request if we attempt to
# relax thresholds explicitly (e.g., BLOCK_NONE or BLOCK_ONLY_HIGH).
SAFETY_SETTINGS = None


def _extract_total_tokens(response) -> int:
    """Pull the total token count from a Gemini response's usage_metadata.

    Returns 0 if the SDK didn't attach usage data (older previews, streamed
    partials, errors). We prefer total_token_count; if absent we sum the
    prompt + candidates counts so cost reporting and the summarization
    trigger still get a meaningful number.
    """
    meta = getattr(response, "usage_metadata", None)
    if not meta:
        return 0
    total = getattr(meta, "total_token_count", None)
    if total is not None:
        return int(total)
    prompt = getattr(meta, "prompt_token_count", 0) or 0
    candidates = getattr(meta, "candidates_token_count", 0) or 0
    return int(prompt) + int(candidates)


def _build_gemini_contents(messages: List[AIMessage], image_bytes: Optional[bytes] = None):
    """Convert internal AIMessages into Gemini ``contents`` + extra system text.

    Enforces Gemini's hard rules so a request can't 400 (which used to make the
    chat appear "frozen" until /new):

    * ``system`` messages (e.g. an injected conversation summary) are pulled out
      — Gemini takes system text via ``config.system_instruction``, NOT as a
      content turn. (Mapping them to a ``model`` turn was the freeze bug.)
    * The first turn MUST be ``user`` — any leading ``model`` turns (which happen
      when the sliding window trims the oldest user message) are dropped.
    * Consecutive same-role turns are merged so roles strictly alternate.

    Returns ``(contents, extra_system_text)``.
    """
    system_chunks: list[str] = []
    turns: list[list] = []  # [role, content, image_bytes|None]
    for msg in messages:
        role_raw = (msg.role or "").lower()
        if role_raw == "system":
            if msg.content:
                system_chunks.append(msg.content)
            continue
        role = "user" if role_raw == "user" else "model"
        turns.append([role, msg.content or "", getattr(msg, "image_bytes", None)])

    # Attach the top-level image to the most recent user turn.
    if image_bytes:
        for turn in reversed(turns):
            if turn[0] == "user":
                turn[2] = turn[2] or image_bytes
                break

    # Gemini requires the conversation to start with a user turn.
    while turns and turns[0][0] != "user":
        turns.pop(0)

    # Merge consecutive same-role turns (keep images on their own turn).
    merged: list[list] = []
    for role, content, img in turns:
        if merged and merged[-1][0] == role and not img and not merged[-1][2]:
            merged[-1][1] = (merged[-1][1] + "\n\n" + content).strip()
        else:
            merged.append([role, content, img])

    contents = []
    for role, content, img in merged:
        parts = []
        if img:
            parts.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))
        parts.append(types.Part.from_text(text=content))
        contents.append(types.Content(role=role, parts=parts))

    return contents, ("\n\n".join(system_chunks) if system_chunks else "")


def _check_response_safety(response) -> None:
    """Check the Gemini response for safety blocks and raise SafetyBlockedError if found."""
    # Check prompt-level block
    if hasattr(response, "prompt_feedback") and response.prompt_feedback:
        block_reason = getattr(response.prompt_feedback, "block_reason", None)
        if block_reason and str(block_reason) not in ("", "BLOCK_REASON_UNSPECIFIED"):
            logger.warning("Gemini prompt blocked: block_reason=%s", block_reason)
            raise SafetyBlockedError(
                category=str(block_reason),
                message="Your prompt was blocked by content safety filters.",
            )

    # Check candidate-level finish_reason
    if response.candidates:
        for candidate in response.candidates:
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason:
                fr_str = str(getattr(finish_reason, "name", finish_reason)).upper()
                if "SAFETY" in fr_str or "BLOCKED" in fr_str:
                    # Try to extract which safety category triggered
                    safety_ratings = getattr(candidate, "safety_ratings", []) or []
                    categories = []
                    for rating in safety_ratings:
                        blocked = getattr(rating, "blocked", False)
                        if blocked:
                            categories.append(str(getattr(rating, "category", "unknown")))
                    cat_str = ", ".join(categories) if categories else "unknown"

                    logger.warning(
                        "Gemini response blocked: finish_reason=%s categories=%s",
                        finish_reason,
                        cat_str,
                    )
                    raise SafetyBlockedError(
                        category=cat_str,
                        message="The AI response was blocked by content safety filters.",
                    )


class AntigravityProvider(BaseAIProvider):
    provider_name = "antigravity"

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    # ── Resilient low-level API call with exponential backoff ─────
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_should_retry_gemini_error),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_gemini(self, *, model_name: str, contents, config):
        """Execute a single Gemini API call with automatic retry on
        transient failures (429, 503, network timeouts, etc.).

        Retries up to 3 attempts with 1s → 2s → 4s exponential backoff.
        Each attempt is guarded by AI_REQUEST_TIMEOUT_SECONDS to prevent
        hanging requests from holding database locks indefinitely.
        """
        return await asyncio.wait_for(
            self.client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            ),
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
        )

    async def generate_text(
        self,
        model_name: str,
        messages: List[AIMessage],
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        image_bytes: Optional[bytes] = None,
        **kwargs
    ) -> AIResponse:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is missing in .env")

        contents, extra_system = _build_gemini_contents(messages, image_bytes)
        if extra_system:
            system_instruction = f"{system_instruction}\n\n{extra_system}" if system_instruction else extra_system

        config = types.GenerateContentConfig()
        if system_instruction:
            config.system_instruction = system_instruction
        if max_tokens:
            config.max_output_tokens = max_tokens
        if kwargs.get("enable_search"):
            config.tools = [{"google_search": {}}]

        try:
            response = await self._call_gemini(
                model_name=model_name,
                contents=contents,
                config=config,
            )

            # Check for safety blocks BEFORE accessing .text
            _check_response_safety(response)

            total_tokens = _extract_total_tokens(response)
            logger.info(
                "Gemini text call model=%s tokens_used=%s",
                model_name,
                total_tokens,
            )
            return AIResponse(
                text=response.text or "",
                model_name=model_name,
                tokens_used=total_tokens,
                finish_reason=str(getattr(response.candidates[0], "finish_reason", "stop")) if response.candidates else "stop",
                raw_metadata={},
            )
        except SafetyBlockedError:
            raise  # Don't wrap safety errors
        except QuotaExhaustedError:
            raise  # already specific
        except Exception as e:
            if _is_quota_error(e):
                logger.error("Gemini quota/billing exhausted: %s", e)
                raise QuotaExhaustedError(str(e))
            logger.error("Gemini API Error (after retries): %s", e, exc_info=True)
            raise RuntimeError(f"AI Generation failed: {e}")

    async def generate_image(self, model_name: str, prompt: str, **kwargs) -> bytes:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is missing")
        try:
            result = await self._call_gemini(
                model_name=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    safety_settings=SAFETY_SETTINGS,
                ),
            )

            # Check for safety blocks
            _check_response_safety(result)

            for candidate in (result.candidates or []):
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            return part.inline_data.data
            raise RuntimeError("No image data returned")
        except SafetyBlockedError:
            raise  # Don't wrap safety errors
        except Exception as e:
            logger.error("Image Error (after retries): %s", e, exc_info=True)
            raise RuntimeError("Image generation failed.")

    async def edit_image(self, model_name: str, prompt: str, image_bytes: bytes, **kwargs) -> bytes:
        """Edit an existing image using a multimodal text+image prompt."""
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is missing")
        try:
            # Build multimodal content: text instruction + source image
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            text_part = types.Part.from_text(text=prompt)

            result = await self._call_gemini(
                model_name=model_name,
                contents=[text_part, image_part],
                config=types.GenerateContentConfig(
                    response_modalities=["Image"],
                    safety_settings=SAFETY_SETTINGS,
                ),
            )

            # Check for safety blocks
            _check_response_safety(result)

            for candidate in (result.candidates or []):
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            return part.inline_data.data
            raise RuntimeError("No edited image data returned")
        except SafetyBlockedError:
            raise
        except Exception as e:
            logger.error("Image edit error (after retries): %s", e, exc_info=True)
            raise RuntimeError("Image editing failed.")
