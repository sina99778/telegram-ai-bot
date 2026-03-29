from __future__ import annotations

import logging
from typing import Protocol, Sequence

from google.genai import types
from app.core.config import settings

logger = logging.getLogger(__name__)

class MessageLike(Protocol):
    role: str
    content: str

class PromptBuilder:
    def __init__(self) -> None:
        self._max_messages = getattr(settings, "MAX_HISTORY_MESSAGES", 10)

    @staticmethod
    def get_system_instruction() -> str:
        import datetime
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        return (
            f"You are 'Nano Banana', a super-intelligent and friendly AI assistant created by Blueprint. "
            f"The current year is 2026 (Today's exact date is {current_date}). "
            f"If the user asks about the date or current events, respond accurately based on the fact that we are in 2026. "
            f"Always be helpful, concise, and occasionally use a banana emoji 🍌."
        )

    def build_messages(
        self,
        system_prompt: str,
        history: Sequence[MessageLike],
        current_user_message: str,
        media_bytes: bytes | None = None,
        mime_type: str | None = None,
    ) -> list[types.Content]:
        
        trimmed = list(history)[-self._max_messages:]
        while trimmed and trimmed[0].role != "user":
            trimmed.pop(0)

        contents = []
        for msg in trimmed:
            contents.append(
                types.Content(role=msg.role, parts=[types.Part.from_text(text=msg.content)])
            )

        user_parts = []
        if media_bytes and mime_type:
            user_parts.append(types.Part.from_bytes(data=media_bytes, mime_type=mime_type))
        
        user_parts.append(types.Part.from_text(text=current_user_message))
        contents.append(types.Content(role="user", parts=user_parts))

        return contents
