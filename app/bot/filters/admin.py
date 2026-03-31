from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.core.access import is_configured_admin

class IsAdmin(BaseFilter):
    """Filter to check if the user is in the admin IDs list."""
    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return is_configured_admin(message.from_user.id)
