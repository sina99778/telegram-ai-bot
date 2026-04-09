import logging
from typing import List, Dict, Optional, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
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


# ── Strict safety settings — block anything flagged LOW or above ──
SAFETY_SETTINGS = [
    types.SafetySetting(
        category="HARM_CATEGORY_HATE_SPEECH",
        threshold="BLOCK_LOW_AND_ABOVE",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
        threshold="BLOCK_LOW_AND_ABOVE",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_DANGEROUS_CONTENT",
        threshold="BLOCK_LOW_AND_ABOVE",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_HARASSMENT",
        threshold="BLOCK_LOW_AND_ABOVE",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_CIVIC_INTEGRITY",
        threshold="BLOCK_LOW_AND_ABOVE",
    ),
]


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
            if finish_reason and str(finish_reason).upper() in ("SAFETY", "BLOCKED"):
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
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_gemini(self, *, model_name: str, contents, config):
        """Execute a single Gemini API call with automatic retry on
        transient failures (429, 503, network timeouts, etc.).

        Retries up to 3 attempts with 1s → 2s → 4s exponential backoff.
        """
        return await self.client.aio.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )

    async def generate_text(
        self,
        model_name: str,
        messages: List[AIMessage],
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AIResponse:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is missing in .env")

        contents = []
        for msg in messages:
            role = "user" if msg.role.lower() == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.content)]))

        config = types.GenerateContentConfig(
            safety_settings=SAFETY_SETTINGS,
        )
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

            return AIResponse(
                text=response.text or "",
                model_name=model_name,
                tokens_used=0,
                finish_reason=str(getattr(response.candidates[0], "finish_reason", "stop")) if response.candidates else "stop",
                raw_metadata={},
            )
        except SafetyBlockedError:
            raise  # Don't wrap safety errors
        except Exception as e:
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

            for candidate in result.candidates:
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
