from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.i18n import t
from app.db.models import User

logger = logging.getLogger(__name__)

# ── Redis-backed membership cache ────────────────────────────────────
# Verified channel members are cached for 12 hours to avoid hitting the
# Telegram API on every single private message.
_FORCED_JOIN_CACHE_TTL = 43200  # 12 hours in seconds
_redis_client: Redis | None = None


async def _get_redis() -> Redis:
    """Lazily initialise the module-level Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _cache_key(user_id: int) -> str:
    return f"forced_join:{user_id}"


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

        user_id = event.from_user.id

        # ── 1. Check Redis cache first ────────────────────────────────
        try:
            redis = await _get_redis()
            cached = await redis.get(_cache_key(user_id))
            if cached:
                # User was verified as a member within the last 12 hours
                return await handler(event, data)
        except Exception as exc:
            # Redis failure must NEVER block users — fall through to API
            logger.warning(
                "Redis cache check failed for forced_join telegram_id=%s error=%s",
                user_id,
                exc,
            )

        # ── 2. Cache miss — call Telegram API ─────────────────────────
        bot = data.get("bot")
        lang = db_user.language if db_user and db_user.language else "fa"

        try:
            member = await bot.get_chat_member(chat_id=settings.FORCED_JOIN_CHANNEL, user_id=user_id)
        except TelegramAPIError as exc:
            logger.warning(
                "Forced-join check failed telegram_id=%s channel=%s error=%s",
                user_id,
                settings.FORCED_JOIN_CHANNEL,
                exc,
                exc_info=True,
            )
            return await handler(event, data)
        except Exception as exc:
            logger.error(
                "Unexpected forced-join middleware error telegram_id=%s channel=%s error=%s",
                user_id,
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
            logger.info("Forced-join blocked telegram_id=%s channel=%s", user_id, settings.FORCED_JOIN_CHANNEL)
            return None

        # ── 3. Verified member — cache in Redis ──────────────────────
        try:
            redis = await _get_redis()
            await redis.set(_cache_key(user_id), "1", ex=_FORCED_JOIN_CACHE_TTL)
        except Exception as exc:
            # Non-critical: next request will just re-verify via API
            logger.warning(
                "Redis cache write failed for forced_join telegram_id=%s error=%s",
                user_id,
                exc,
            )

        return await handler(event, data)
