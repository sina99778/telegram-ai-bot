from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.styling import colorize_inline_markup
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


async def _resolve_config(session: AsyncSession | None) -> tuple[bool, str]:
    """Effective (enabled, channel), read from the admin-editable RuntimeConfig
    and falling back to the env defaults if the DB isn't reachable."""
    if session is not None:
        try:
            from app.services.config.runtime_config import RuntimeConfig

            enabled = (await RuntimeConfig.get_int(session, "forced_join_enabled")) == 1
            channel = (await RuntimeConfig.get_text(session, "forced_join_channel") or "").strip()
            return enabled, channel
        except Exception:
            pass
    return bool(settings.FORCED_JOIN_REQUIRED), (settings.FORCED_JOIN_CHANNEL or "").strip()


async def clear_membership_cache() -> None:
    """Drop all cached membership verdicts — call when the channel/toggle changes
    so a new requirement is enforced immediately (not after the 12h TTL)."""
    try:
        redis = await _get_redis()
        async for key in redis.scan_iter(match="forced_join:*"):
            await redis.delete(key)
    except Exception:
        logger.warning("Could not clear forced-join membership cache", exc_info=True)


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

        enabled, channel = await _resolve_config(session)
        if not enabled or not channel:
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
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        except TelegramAPIError as exc:
            logger.warning(
                "Forced-join check failed telegram_id=%s channel=%s error=%s",
                user_id,
                channel,
                exc,
                exc_info=True,
            )
            return await handler(event, data)
        except Exception as exc:
            logger.error(
                "Unexpected forced-join middleware error telegram_id=%s channel=%s error=%s",
                user_id,
                channel,
                exc,
                exc_info=True,
            )
            return await handler(event, data)

        if member.status in {"left", "kicked", "banned"}:
            join_url = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"
            kb = colorize_inline_markup(InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=t(lang, "forced_join.join_button"),
                            url=join_url,
                        )
                    ]
                ]
            ))
            await event.answer(
                t(lang, "forced_join.required"),
                reply_markup=kb,
                parse_mode="HTML",
            )
            logger.info("Forced-join blocked telegram_id=%s channel=%s", user_id, channel)
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
