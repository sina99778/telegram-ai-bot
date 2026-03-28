"""
app/ai/prompt_builder.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Converts database conversation history into the dict-based format
expected by the Google GenAI SDK ``contents`` parameter.

Responsibilities:
  • Map SQLAlchemy ``Message`` objects → GenAI content dicts
  • Enforce context-window limits (message count + character budget)
  • Provide the system instruction from application settings
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Protocol, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  Structural type for the Message ORM model
# ──────────────────────────────────────────────
class MessageLike(Protocol):
    """Duck-type protocol so we don't couple to the concrete ORM class.

    Any object with ``.role`` and ``.content`` string attributes satisfies
    this contract — including the SQLAlchemy ``Message`` model from
    ``app.db.models.message``.
    """

    role: str
    content: str


# ──────────────────────────────────────────────
#  Constants / defaults
# ──────────────────────────────────────────────
_DEFAULT_MAX_HISTORY_MESSAGES: int = 10
_APPROX_CHARS_PER_TOKEN: int = 4  # rough heuristic (English text)


# ──────────────────────────────────────────────
#  Prompt Builder
# ──────────────────────────────────────────────
class PromptBuilder:
    """Builds a Gemini-compatible ``contents`` list from raw DB history.

    Usage::

        builder  = PromptBuilder()
        system   = builder.get_system_instruction()
        messages = builder.build_messages(
            system_prompt=system,
            history=db_messages,
            current_user_message="What's the weather?",
        )
        # Pass *messages* to genai's ``contents`` and *system* to
        # ``config.system_instruction``.
    """

    def __init__(
        self,
        max_history_messages: int | None = None,
        max_context_chars: int | None = None,
    ) -> None:
        """
        Parameters
        ----------
        max_history_messages:
            Maximum number of history messages to keep.  Defaults to
            ``settings.MAX_HISTORY_MESSAGES`` if available, otherwise 10.
        max_context_chars:
            Approximate character budget for the combined history.
            Derived from ``settings.MAX_CONTEXT_TOKENS`` (× 4 chars/token)
            when not supplied explicitly.
        """
        self._max_messages: int = (
            max_history_messages
            or getattr(settings, "MAX_HISTORY_MESSAGES", None)
            or _DEFAULT_MAX_HISTORY_MESSAGES
        )

        # Derive a character budget from the token limit in settings
        token_limit: int | None = getattr(settings, "MAX_CONTEXT_TOKENS", None)
        self._max_chars: int | None = (
            max_context_chars
            or (token_limit * _APPROX_CHARS_PER_TOKEN if token_limit else None)
        )

        logger.info(
            "PromptBuilder initialised  ·  max_messages=%d  ·  max_chars=%s",
            self._max_messages,
            self._max_chars or "unlimited",
        )

    # ── public helpers ───────────────────────────

    @staticmethod
    def get_system_instruction() -> str:
        """Return the system prompt stored in application settings.

        Falls back to a sensible default if ``settings.SYSTEM_PROMPT`` is
        not defined.
        """
        return getattr(
            settings,
            "SYSTEM_PROMPT",
            "You are a helpful AI assistant.",
        )

    # ── main builder ─────────────────────────────

    def build_messages(
        self,
        system_prompt: str,
        history: Sequence[MessageLike],
        current_user_message: str,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
    ) -> list[dict[str, Any]]:
        """Build the ``contents`` list for ``generate_content()``.

        Parameters
        ----------
        system_prompt:
            The system-level instruction.  *Not* included in the returned
            list — pass it separately via
            ``types.GenerateContentConfig(system_instruction=...)``.
            It is accepted here so callers can override / log it
            alongside the rest of the context.
        history:
            Ordered list of past ``Message`` ORM instances.  Each must
            expose ``.role`` (``"user"`` | ``"model"``) and ``.content``.
        current_user_message:
            The latest message from the user that triggered this call.
        image_bytes:
            Optional raw bytes of an image attachment.  When provided,
            the final user turn will include an ``inline_data`` part
            alongside the text.
        mime_type:
            MIME type of the attached image (default ``"image/jpeg"``).

        Returns
        -------
        list[dict[str, Any]]
            A list of dicts with ``role`` and ``parts`` keys, ready to
            be passed as ``contents`` to the GenAI SDK::

                [
                    {"role": "user",  "parts": [{"text": "Hi"}]},
                    {"role": "model", "parts": [{"text": "Hello!"}]},
                    ...
                ]
        """
        # 1. Trim history to the allowed window
        trimmed = self._trim_history(list(history))

        # 2. Convert ORM objects → GenAI content dicts
        contents: list[dict[str, Any]] = [
            self._message_to_dict(msg) for msg in trimmed
        ]

        # 3. Append the current user turn (optionally with an image)
        if image_bytes is not None:
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            user_parts: list[dict[str, Any]] = [
                {"inline_data": {"mime_type": mime_type, "data": b64_data}},
                {"text": current_user_message},
            ]
            contents.append({"role": "user", "parts": user_parts})
            logger.info(
                "Attached image  ·  mime=%s  ·  size=%d bytes",
                mime_type,
                len(image_bytes),
            )
        else:
            contents.append(self._text_to_dict("user", current_user_message))

        logger.info(
            "Prompt built  ·  history_kept=%d/%d  ·  total_turns=%d",
            len(trimmed),
            len(history),
            len(contents),
        )
        return contents

    # ── private helpers ──────────────────────────

    def _trim_history(
        self,
        history: list[MessageLike],
    ) -> list[MessageLike]:
        """Trim *history* so it fits within both message-count and
        character-budget limits.

        The most recent messages are always preserved (we slice from the
        tail).
        """
        # --- cap by message count ---
        if len(history) > self._max_messages:
            logger.debug(
                "Trimming history by count: %d → %d",
                len(history),
                self._max_messages,
            )
            history = history[-self._max_messages :]

        # --- cap by character budget (if configured) ---
        if self._max_chars is not None:
            total_chars = 0
            cutoff_index = len(history)

            # Walk backwards (newest first) accumulating characters
            for i in range(len(history) - 1, -1, -1):
                total_chars += len(history[i].content)
                if total_chars > self._max_chars:
                    cutoff_index = i + 1
                    break

            if cutoff_index > 0 and cutoff_index < len(history):
                logger.debug(
                    "Trimming history by char budget (%d chars): %d → %d msgs",
                    self._max_chars,
                    len(history),
                    len(history) - cutoff_index,
                )
                history = history[cutoff_index:]

        # Ensure the conversation starts with a "user" turn (Gemini
        # requires the first content to be from the user).
        while history and history[0].role != "user":
            history.pop(0)

        return history

    @staticmethod
    def _message_to_dict(msg: MessageLike) -> dict[str, Any]:
        """Convert a single ``Message`` ORM instance to a GenAI dict."""
        return {
            "role": msg.role,
            "parts": [{"text": msg.content}],
        }

    @staticmethod
    def _text_to_dict(role: str, text: str) -> dict[str, Any]:
        """Create a GenAI content dict from raw role + text."""
        return {
            "role": role,
            "parts": [{"text": text}],
        }
