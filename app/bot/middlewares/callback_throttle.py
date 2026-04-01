from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

from app.services.security.abuse_guard import AbuseGuardService


class CallbackThrottleMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if not event.from_user:
            return await handler(event, data)

        lang = "fa"
        db_user = data.get("db_user")
        if db_user and getattr(db_user, "language", None):
            lang = db_user.language

        decision = AbuseGuardService.check_callback(user_id=event.from_user.id, lang=lang)
        if not decision.allowed:
            await event.answer(decision.reason or "", show_alert=False)
            return None

        return await handler(event, data)
