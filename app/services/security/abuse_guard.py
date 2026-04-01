from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings
from app.core.i18n import t

logger = logging.getLogger(__name__)


@dataclass
class GuardDecision:
    allowed: bool
    reason: str | None = None


class AbuseGuardService:
    """Redis-backed anti-abuse guard for shared throttling and temporary blocks."""

    _client: Redis | None = None

    @classmethod
    def _now_ts(cls) -> float:
        return datetime.now(timezone.utc).timestamp()

    @classmethod
    async def get_client(cls) -> Redis:
        if cls._client is None:
            cls._client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._client

    @classmethod
    def _backend_error_decision(cls, lang: str) -> GuardDecision:
        logger.error("Abuse guard backend unavailable; denying guarded action")
        return GuardDecision(allowed=False, reason=t(lang, "abuse.guard_unavailable"))

    @classmethod
    async def set_client_for_tests(cls, client: Redis | Any) -> None:
        cls._client = client

    @classmethod
    async def reset_for_tests(cls) -> None:
        if cls._client and hasattr(cls._client, "flushdb"):
            await cls._client.flushdb()
        cls._client = None

    @classmethod
    def _events_key(cls, subject: str, subject_id: int) -> str:
        return f"abuse:events:{subject}:{subject_id}"

    @classmethod
    def _failures_key(cls, subject: str, subject_id: int) -> str:
        return f"abuse:failures:{subject}:{subject_id}"

    @classmethod
    def _block_key(cls, subject: str, subject_id: int) -> str:
        return f"abuse:block:{subject}:{subject_id}"

    @classmethod
    def _parse_subject_key(cls, key: str, prefix: str) -> tuple[str, int]:
        tail = key.removeprefix(prefix)
        subject, subject_id = tail.rsplit(":", 1)
        return subject, int(subject_id)

    @classmethod
    async def _check_temp_block(cls, *, subject: str, subject_id: int, lang: str) -> GuardDecision:
        client = await cls.get_client()
        ttl = await client.ttl(cls._block_key(subject, subject_id))
        if ttl and ttl > 0:
            return GuardDecision(allowed=False, reason=t(lang, "abuse.temp_blocked", seconds=ttl))
        return GuardDecision(allowed=True)

    @classmethod
    async def _hit_window(
        cls,
        *,
        subject: str,
        subject_id: int,
        limit: int,
        window_seconds: int,
        lang: str,
        reason_key: str,
        reason_kwargs: dict | None = None,
    ) -> GuardDecision:
        block_decision = await cls._check_temp_block(subject=subject, subject_id=subject_id, lang=lang)
        if not block_decision.allowed:
            return block_decision

        client = await cls.get_client()
        key = cls._events_key(subject, subject_id)
        now = cls._now_ts()
        member = f"{now}:{uuid.uuid4().hex}"
        cutoff = now - window_seconds
        async with client.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            current = await pipe.execute()
        current_count = int(current[1] or 0)
        if current_count >= limit:
            kwargs = reason_kwargs or {}
            return GuardDecision(allowed=False, reason=t(lang, reason_key, **kwargs))

        async with client.pipeline(transaction=True) as pipe:
            pipe.zadd(key, {member: now})
            pipe.expire(key, window_seconds + 60)
            await pipe.execute()
        return GuardDecision(allowed=True)

    @classmethod
    async def check_private_chat(cls, *, user_id: int, lang: str) -> GuardDecision:
        try:
            return await cls._hit_window(
                subject="private_chat",
                subject_id=user_id,
                limit=settings.PRIVATE_MESSAGE_BURST_LIMIT,
                window_seconds=settings.PRIVATE_MESSAGE_BURST_WINDOW_SECONDS,
                lang=lang,
                reason_key="abuse.private_chat_rate_limited",
            )
        except Exception:
            logger.exception("Abuse guard failed for private chat user_id=%s", user_id)
            return cls._backend_error_decision(lang)

    @classmethod
    async def check_search(cls, *, scope_id: int, is_group: bool, lang: str) -> GuardDecision:
        try:
            return await cls._hit_window(
                subject="group_search" if is_group else "user_search",
                subject_id=scope_id,
                limit=1,
                window_seconds=settings.SEARCH_COMMAND_COOLDOWN_SECONDS,
                lang=lang,
                reason_key="abuse.search_rate_limited",
                reason_kwargs={"seconds": settings.SEARCH_COMMAND_COOLDOWN_SECONDS},
            )
        except Exception:
            logger.exception("Abuse guard failed for search scope_id=%s is_group=%s", scope_id, is_group)
            return cls._backend_error_decision(lang)

    @classmethod
    async def check_image(cls, *, user_id: int, lang: str) -> GuardDecision:
        try:
            return await cls._hit_window(
                subject="image",
                subject_id=user_id,
                limit=1,
                window_seconds=settings.IMAGE_COMMAND_COOLDOWN_SECONDS,
                lang=lang,
                reason_key="abuse.image_rate_limited",
                reason_kwargs={"seconds": settings.IMAGE_COMMAND_COOLDOWN_SECONDS},
            )
        except Exception:
            logger.exception("Abuse guard failed for image user_id=%s", user_id)
            return cls._backend_error_decision(lang)

    @classmethod
    async def check_callback(cls, *, user_id: int, lang: str) -> GuardDecision:
        try:
            return await cls._hit_window(
                subject="callback",
                subject_id=user_id,
                limit=1,
                window_seconds=settings.CALLBACK_COOLDOWN_SECONDS,
                lang=lang,
                reason_key="abuse.callback_rate_limited",
                reason_kwargs={"seconds": settings.CALLBACK_COOLDOWN_SECONDS},
            )
        except Exception:
            logger.exception("Abuse guard failed for callback user_id=%s", user_id)
            return cls._backend_error_decision(lang)

    @classmethod
    async def check_admin_action(cls, *, admin_id: int, action: str, lang: str) -> GuardDecision:
        try:
            return await cls._hit_window(
                subject=f"admin:{action}",
                subject_id=admin_id,
                limit=1,
                window_seconds=settings.ADMIN_ACTION_COOLDOWN_SECONDS,
                lang=lang,
                reason_key="abuse.admin_rate_limited",
                reason_kwargs={"seconds": settings.ADMIN_ACTION_COOLDOWN_SECONDS},
            )
        except Exception:
            logger.exception("Abuse guard failed for admin action admin_id=%s action=%s", admin_id, action)
            return cls._backend_error_decision(lang)

    @classmethod
    def enforce_prompt_length(cls, *, prompt: str, limit: int, lang: str) -> GuardDecision:
        if len(prompt) > limit:
            return GuardDecision(allowed=False, reason=t(lang, "abuse.prompt_too_long", limit=limit))
        return GuardDecision(allowed=True)

    @classmethod
    async def record_failure(cls, *, subject: str, subject_id: int) -> None:
        try:
            client = await cls.get_client()
            key = cls._failures_key(subject, subject_id)
            now = cls._now_ts()
            member = f"{now}:{uuid.uuid4().hex}"
            cutoff = now - settings.ABUSE_FAILURE_WINDOW_SECONDS
            async with client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zadd(key, {member: now})
                pipe.zcard(key)
                pipe.expire(key, settings.ABUSE_FAILURE_WINDOW_SECONDS + 60)
                _, _, count, _ = await pipe.execute()
            if int(count or 0) >= settings.ABUSE_FAILURE_THRESHOLD:
                block_key = cls._block_key(subject, subject_id)
                await client.set(block_key, "1", ex=settings.ABUSE_TEMP_BLOCK_SECONDS)
                logger.warning("Abuse temp block applied subject=%s subject_id=%s", subject, subject_id)
        except Exception:
            logger.exception("Failed to record abuse failure subject=%s subject_id=%s", subject, subject_id)

    @classmethod
    async def list_temp_blocks(cls, limit: int = 20) -> list[dict[str, Any]]:
        try:
            client = await cls.get_client()
            items: list[dict[str, Any]] = []
            async for key in client.scan_iter(match="abuse:block:*"):
                ttl = await client.ttl(key)
                subject, subject_id = cls._parse_subject_key(key, "abuse:block:")
                items.append({"subject": subject, "subject_id": int(subject_id), "ttl": max(ttl, 0)})
                if len(items) >= limit:
                    break
            return items
        except Exception:
            logger.exception("Failed to list temporary abuse blocks")
            return []

    @classmethod
    async def list_recent_failures(cls, limit: int = 20) -> list[dict[str, Any]]:
        try:
            client = await cls.get_client()
            items: list[dict[str, Any]] = []
            async for key in client.scan_iter(match="abuse:failures:*"):
                count = await client.zcard(key)
                if not count:
                    continue
                subject, subject_id = cls._parse_subject_key(key, "abuse:failures:")
                items.append({"subject": subject, "subject_id": int(subject_id), "count": int(count)})
                if len(items) >= limit:
                    break
            items.sort(key=lambda item: item["count"], reverse=True)
            return items[:limit]
        except Exception:
            logger.exception("Failed to list recent abuse failures")
            return []
