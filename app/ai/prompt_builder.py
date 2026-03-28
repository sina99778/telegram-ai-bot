from __future__ import annotations

import logging
import base64
from typing import Any, Protocol, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)

class MessageLike(Protocol):
    role: str
    content: str

_DEFAULT_MAX_HISTORY_MESSAGES: int = 10
_APPROX_CHARS_PER_TOKEN: int = 4

class PromptBuilder:
    def __init__(self, max_history_messages: int | None = None, max_context_chars: int | None = None) -> None:
        self._max_messages: int = max_history_messages or getattr(settings, "MAX_HISTORY_MESSAGES", None) or _DEFAULT_MAX_HISTORY_MESSAGES
        token_limit: int | None = getattr(settings, "MAX_CONTEXT_TOKENS", None)
        self._max_chars: int | None = max_context_chars or (token_limit * _APPROX_CHARS_PER_TOKEN if token_limit else None)

    @staticmethod
    def get_system_instruction() -> str:
        return getattr(settings, "SYSTEM_PROMPT", "You are a helpful AI assistant.")

    def build_messages(
        self,
        system_prompt: str,
        history: Sequence[MessageLike],
        current_user_message: str,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
    ) -> list[dict[str, Any]]:
        
        trimmed = self._trim_history(list(history))
        contents: list[dict[str, Any]] = [self._message_to_dict(msg) for msg in trimmed]

        user_parts = []
        if image_bytes:
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            user_parts.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})
        
        user_parts.append({"text": current_user_message})
        contents.append({"role": "user", "parts": user_parts})

        return contents

    def _trim_history(self, history: list[MessageLike]) -> list[MessageLike]:
        if len(history) > self._max_messages:
            history = history[-self._max_messages :]
        if self._max_chars is not None:
            total_chars = 0
            cutoff_index = len(history)
            for i in range(len(history) - 1, -1, -1):
                total_chars += len(history[i].content)
                if total_chars > self._max_chars:
                    cutoff_index = i + 1
                    break
            if cutoff_index > 0 and cutoff_index < len(history):
                history = history[cutoff_index:]
        while history and history[0].role != "user":
            history.pop(0)
        return history

    @staticmethod
    def _message_to_dict(msg: MessageLike) -> dict[str, Any]:
        return {"role": msg.role, "parts": [{"text": msg.content}]}
