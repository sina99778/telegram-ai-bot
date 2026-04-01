from __future__ import annotations

import json
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
    def _anomaly_window_key(cls, scope_type: str, scope_id: int, feature: str) -> str:
        return f"abuse:anomaly_window:{scope_type}:{scope_id}:{feature}"

    @classmethod
    def _anomaly_flag_key(cls, scope_type: str, scope_id: int, feature: str) -> str:
        return f"abuse:anomaly:{scope_type}:{scope_id}:{feature}"

    @classmethod
    def _global_user_block_key(cls, user_id: int) -> str:
        return cls._block_key("user", user_id)

    @classmethod
    def _global_group_block_key(cls, group_id: int) -> str:
        return cls._block_key("group", group_id)

    @classmethod
    def _parse_subject_key(cls, key: str, prefix: str) -> tuple[str, int]:
        tail = key.removeprefix(prefix)
        subject, subject_id = tail.rsplit(":", 1)
        return subject, int(subject_id)

    @classmethod
    async def _check_temp_block(cls, *, subject: str, subject_id: int, lang: str) -> GuardDecision:
        client = await cls.get_client()
        keys = [cls._block_key(subject, subject_id)]
        if subject in {"private_chat", "user_search", "image", "callback"} or subject.startswith("admin:"):
            keys.append(cls._global_user_block_key(subject_id))
        if subject in {"group_request", "group_search"}:
            keys.append(cls._global_group_block_key(subject_id))
        ttl = 0
        for key in keys:
            key_ttl = await client.ttl(key)
            if key_ttl and key_ttl > ttl:
                ttl = key_ttl
        if ttl > 0:
            return GuardDecision(allowed=False, reason=t(lang, "abuse.temp_blocked", seconds=ttl))
        return GuardDecision(allowed=True)

    @classmethod
    async def _flag_anomaly(
        cls,
        *,
        scope_type: str,
        scope_id: int,
        feature: str,
        count: int,
        contain_seconds: int,
        contain_subject: str | None = None,
        contain_subject_id: int | None = None,
    ) -> None:
        client = await cls.get_client()
        payload = json.dumps({"count": count, "ts": int(cls._now_ts())})
        await client.set(cls._anomaly_flag_key(scope_type, scope_id, feature), payload, ex=contain_seconds)
        if contain_subject is not None and contain_subject_id is not None:
            await client.set(cls._block_key(contain_subject, contain_subject_id), "1", ex=contain_seconds)
        if scope_type == "user":
            await client.set(cls._global_user_block_key(scope_id), "1", ex=contain_seconds)
        elif scope_type == "group":
            await client.set(cls._global_group_block_key(scope_id), "1", ex=contain_seconds)

    @classmethod
    async def _track_anomaly_window(
        cls,
        *,
        scope_type: str,
        scope_id: int,
        feature: str,
        threshold: int,
        window_seconds: int,
        contain_seconds: int,
        contain_subject: str | None = None,
        contain_subject_id: int | None = None,
    ) -> None:
        client = await cls.get_client()
        key = cls._anomaly_window_key(scope_type, scope_id, feature)
        now = cls._now_ts()
        member = f"{now}:{uuid.uuid4().hex}"
        cutoff = now - window_seconds
        async with client.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zadd(key, {member: now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds + 60)
            _, _, count, _ = await pipe.execute()
        if int(count or 0) >= threshold:
            logger.warning(
                "Anomaly detected scope_type=%s scope_id=%s feature=%s count=%s",
                scope_type,
                scope_id,
                feature,
                count,
            )
            await cls._flag_anomaly(
                scope_type=scope_type,
                scope_id=scope_id,
                feature=feature,
                count=int(count or 0),
                contain_seconds=contain_seconds,
                contain_subject=contain_subject,
                contain_subject_id=contain_subject_id,
            )

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
            decision = await cls._hit_window(
                subject="private_chat",
                subject_id=user_id,
                limit=settings.PRIVATE_MESSAGE_BURST_LIMIT,
                window_seconds=settings.PRIVATE_MESSAGE_BURST_WINDOW_SECONDS,
                lang=lang,
                reason_key="abuse.private_chat_rate_limited",
            )
            if decision.allowed:
                await cls._track_anomaly_window(
                    scope_type="user",
                    scope_id=user_id,
                    feature="request_volume",
                    threshold=settings.USER_ANOMALY_REQUEST_THRESHOLD,
                    window_seconds=settings.USER_ANOMALY_WINDOW_SECONDS,
                    contain_seconds=settings.ANOMALY_CONTAIN_SECONDS,
                )
            return decision
        except Exception:
            logger.exception("Abuse guard failed for private chat user_id=%s", user_id)
            return cls._backend_error_decision(lang)

    @classmethod
    async def check_group_request(cls, *, group_id: int, lang: str) -> GuardDecision:
        try:
            decision = await cls._check_temp_block(subject="group_request", subject_id=group_id, lang=lang)
            if not decision.allowed:
                return decision
            await cls._track_anomaly_window(
                scope_type="group",
                scope_id=group_id,
                feature="request_volume",
                threshold=settings.GROUP_ANOMALY_REQUEST_THRESHOLD,
                window_seconds=settings.GROUP_ANOMALY_WINDOW_SECONDS,
                contain_seconds=settings.ANOMALY_CONTAIN_SECONDS,
                contain_subject="group_request",
                contain_subject_id=group_id,
            )
            return GuardDecision(allowed=True)
        except Exception:
            logger.exception("Abuse guard failed for group request group_id=%s", group_id)
            return cls._backend_error_decision(lang)

    @classmethod
    async def check_search(cls, *, scope_id: int, is_group: bool, lang: str) -> GuardDecision:
        try:
            subject = "group_search" if is_group else "user_search"
            decision = await cls._hit_window(
                subject=subject,
                subject_id=scope_id,
                limit=1,
                window_seconds=settings.SEARCH_COMMAND_COOLDOWN_SECONDS,
                lang=lang,
                reason_key="abuse.search_rate_limited",
                reason_kwargs={"seconds": settings.SEARCH_COMMAND_COOLDOWN_SECONDS},
            )
            if decision.allowed:
                await cls._track_anomaly_window(
                    scope_type="group" if is_group else "user",
                    scope_id=scope_id,
                    feature="search_burst",
                    threshold=settings.EXPENSIVE_COMMAND_BURST_THRESHOLD,
                    window_seconds=settings.EXPENSIVE_COMMAND_BURST_WINDOW_SECONDS,
                    contain_seconds=settings.FEATURE_CONTAIN_SECONDS,
                    contain_subject=subject,
                    contain_subject_id=scope_id,
                )
            return decision
        except Exception:
            logger.exception("Abuse guard failed for search scope_id=%s is_group=%s", scope_id, is_group)
            return cls._backend_error_decision(lang)

    @classmethod
    async def check_image(cls, *, user_id: int, lang: str) -> GuardDecision:
        try:
            decision = await cls._hit_window(
                subject="image",
                subject_id=user_id,
                limit=1,
                window_seconds=settings.IMAGE_COMMAND_COOLDOWN_SECONDS,
                lang=lang,
                reason_key="abuse.image_rate_limited",
                reason_kwargs={"seconds": settings.IMAGE_COMMAND_COOLDOWN_SECONDS},
            )
            if decision.allowed:
                await cls._track_anomaly_window(
                    scope_type="user",
                    scope_id=user_id,
                    feature="image_burst",
                    threshold=settings.EXPENSIVE_COMMAND_BURST_THRESHOLD,
                    window_seconds=settings.EXPENSIVE_COMMAND_BURST_WINDOW_SECONDS,
                    contain_seconds=settings.FEATURE_CONTAIN_SECONDS,
                    contain_subject="image",
                    contain_subject_id=user_id,
                )
            return decision
        except Exception:
            logger.exception("Abuse guard failed for image user_id=%s", user_id)
            return cls._backend_error_decision(lang)

    @classmethod
    async def check_callback(cls, *, user_id: int, lang: str) -> GuardDecision:
        try:
            decision = await cls._hit_window(
                subject="callback",
                subject_id=user_id,
                limit=1,
                window_seconds=settings.CALLBACK_COOLDOWN_SECONDS,
                lang=lang,
                reason_key="abuse.callback_rate_limited",
                reason_kwargs={"seconds": settings.CALLBACK_COOLDOWN_SECONDS},
            )
            if decision.allowed:
                await cls._track_anomaly_window(
                    scope_type="user",
                    scope_id=user_id,
                    feature="callback_spam",
                    threshold=settings.CALLBACK_SPAM_THRESHOLD,
                    window_seconds=settings.CALLBACK_SPAM_WINDOW_SECONDS,
                    contain_seconds=settings.FEATURE_CONTAIN_SECONDS,
                    contain_subject="callback",
                    contain_subject_id=user_id,
                )
            return decision
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
                scope_type = "group" if subject.startswith("group") else "user"
                await cls._flag_anomaly(
                    scope_type=scope_type,
                    scope_id=subject_id,
                    feature="failure_storm",
                    count=int(count or 0),
                    contain_seconds=settings.ABUSE_TEMP_BLOCK_SECONDS,
                    contain_subject=subject,
                    contain_subject_id=subject_id,
                )
                logger.warning("Abuse temp block applied subject=%s subject_id=%s", subject, subject_id)
        except Exception:
            logger.exception("Failed to record abuse failure subject=%s subject_id=%s", subject, subject_id)

    @classmethod
    async def list_active_anomalies(cls, limit: int = 20) -> list[dict[str, Any]]:
        try:
            client = await cls.get_client()
            items: list[dict[str, Any]] = []
            async for key in client.scan_iter(match="abuse:anomaly:*"):
                raw = await client.get(key)
                ttl = await client.ttl(key)
                if not raw:
                    continue
                data = json.loads(raw)
                tail = key.removeprefix("abuse:anomaly:")
                scope_type, scope_id, feature = tail.split(":", 2)
                items.append(
                    {
                        "scope_type": scope_type,
                        "scope_id": int(scope_id),
                        "feature": feature,
                        "count": int(data.get("count", 0)),
                        "ttl": max(ttl, 0),
                    }
                )
                if len(items) >= limit:
                    break
            items.sort(key=lambda item: (item["count"], item["ttl"]), reverse=True)
            return items[:limit]
        except Exception:
            logger.exception("Failed to list active anomalies")
            return []

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
