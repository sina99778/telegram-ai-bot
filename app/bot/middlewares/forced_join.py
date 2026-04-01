from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.i18n import t
from app.db.models import User

logger = logging.getLogger(__name__)


class CheckUserStatusMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not event.from_user:
            return await handler(event, data)

        session: AsyncSession = data.get("session")
        db_user: User | None = None
        if session:
            db_user = await session.scalar(select(User).where(User.telegram_id == event.from_user.id))
            if db_user and db_user.is_banned:
                logger.info("Blocked banned user update telegram_id=%s", event.from_user.id)
                return None

        if getattr(event, "chat", None) and event.chat.type != "private":
            return await handler(event, data)

        if not settings.FORCED_JOIN_REQUIRED or not settings.FORCED_JOIN_CHANNEL:
            return await handler(event, data)

        bot = data.get("bot")
        lang = db_user.language if db_user and db_user.language else "fa"

        try:
            member = await bot.get_chat_member(chat_id=settings.FORCED_JOIN_CHANNEL, user_id=event.from_user.id)
        except TelegramAPIError as exc:
            logger.warning(
                "Forced-join check failed telegram_id=%s channel=%s error=%s",
                event.from_user.id,
                settings.FORCED_JOIN_CHANNEL,
                exc,
                exc_info=True,
            )
            return await handler(event, data)
        except Exception as exc:
            logger.error(
                "Unexpected forced-join middleware error telegram_id=%s channel=%s error=%s",
                event.from_user.id,
                settings.FORCED_JOIN_CHANNEL,
                exc,
                exc_info=True,
            )
            return await handler(event, data)

        if member.status in {"left", "kicked", "banned"}:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📢 Join Channel",
                            url=f"https://t.me/{settings.FORCED_JOIN_CHANNEL.lstrip('@')}",
                        )
                    ]
                ]
            )
            await event.answer(
                t(lang, "forced_join.required"),
                reply_markup=kb,
                parse_mode="HTML",
            )
            logger.info("Forced-join blocked telegram_id=%s channel=%s", event.from_user.id, settings.FORCED_JOIN_CHANNEL)
            return None

        return await handler(event, data)
