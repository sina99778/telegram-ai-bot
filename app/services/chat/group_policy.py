from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from redis.asyncio import Redis

from app.core.config import settings
from app.core.i18n import t

logger = logging.getLogger(__name__)


@dataclass
class GroupPolicyDecision:
    allowed: bool
    reason: str | None = None


class GroupPolicyService:
    """Group usage guardrails.

    Daily counters (``group_daily`` / ``user_daily``) are persisted in Redis
    so a bot restart does not wipe the per-group/per-user caps. Cooldown
    timestamps and message dedup keys stay in-memory because their TTL is
    measured in seconds.
    """

    # ── In-memory state (transient by design) ──────────────────
    _day_marker: date | None = None
    _last_user_message_at: dict[tuple[int, int], datetime] = {}
    _handled_messages: dict[tuple[int, int], datetime] = {}
    _handled_ttl_seconds: int = 60

    # ── Test/in-memory fallback for daily counts ──
    _group_counts: dict[int, int] = {}
    _user_counts: dict[tuple[int, int], int] = {}

    # ── Lazy Redis client (None ⇒ fall back to in-memory) ──────
    _redis: Redis | None = None
    _redis_disabled: bool = False

    @classmethod
    async def _get_redis(cls) -> Redis | None:
        if cls._redis_disabled:
            return None
        if cls._redis is None:
            try:
                cls._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            except Exception as exc:
                logger.warning("GroupPolicy redis unavailable; using in-memory fallback error=%s", exc)
                cls._redis_disabled = True
                return None
        return cls._redis

    @classmethod
    def _today(cls) -> date:
        return datetime.now(timezone.utc).date()

    @classmethod
    def _seconds_until_midnight_utc(cls) -> int:
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, int((tomorrow - now).total_seconds()))

    @classmethod
    def _group_key(cls, group_id: int) -> str:
        return f"group_policy:daily:group:{cls._today().isoformat()}:{group_id}"

    @classmethod
    def _user_key(cls, group_id: int, user_id: int) -> str:
        return f"group_policy:daily:user:{cls._today().isoformat()}:{group_id}:{user_id}"

    @classmethod
    def _reset_transient_if_needed(cls) -> None:
        today = cls._today()
        if cls._day_marker != today:
            cls._day_marker = today
            cls._last_user_message_at = {}
            cls._handled_messages = {}
            cls._group_counts = {}
            cls._user_counts = {}
        else:
            cls._prune_handled_messages()

    @classmethod
    def _prune_handled_messages(cls) -> None:
        now = datetime.now(timezone.utc)
        cls._handled_messages = {
            key: seen_at
            for key, seen_at in cls._handled_messages.items()
            if now - seen_at < timedelta(seconds=cls._handled_ttl_seconds)
        }

    @classmethod
    def claim_message(cls, *, group_id: int, message_id: int) -> bool:
        cls._reset_transient_if_needed()
        key = (group_id, message_id)
        if key in cls._handled_messages:
            return False
        cls._handled_messages[key] = datetime.now(timezone.utc)
        return True

    @classmethod
    def check_cooldown(cls, *, group_id: int, user_id: int, lang: str = "en") -> GroupPolicyDecision:
        cls._reset_transient_if_needed()
        now = datetime.now(timezone.utc)
        user_key = (group_id, user_id)
        last_seen = cls._last_user_message_at.get(user_key)
        if last_seen and now - last_seen < timedelta(seconds=settings.GROUP_USER_COOLDOWN_SECONDS):
            remaining = settings.GROUP_USER_COOLDOWN_SECONDS - int((now - last_seen).total_seconds())
            return GroupPolicyDecision(
                allowed=False,
                reason=t(lang, "group.cooldown", seconds=remaining),
            )
        return GroupPolicyDecision(allowed=True)

    @classmethod
    async def _read_daily_count(cls, key: str) -> int:
        redis = await cls._get_redis()
        if redis is None:
            return 0
        try:
            raw = await redis.get(key)
        except Exception as exc:
            logger.warning("GroupPolicy redis GET failed key=%s error=%s", key, exc)
            return 0
        try:
            return int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    @classmethod
    async def evaluate(
        cls,
        *,
        group_id: int,
        user_id: int,
        prompt: str,
        lang: str = "en",
    ) -> GroupPolicyDecision:
        cls._reset_transient_if_needed()

        if len(prompt) > settings.GROUP_MAX_PROMPT_LENGTH:
            return GroupPolicyDecision(
                allowed=False,
                reason=t(lang, "group.prompt_limit", limit=settings.GROUP_MAX_PROMPT_LENGTH),
            )

        redis = await cls._get_redis()
        if redis is not None:
            group_count = await cls._read_daily_count(cls._group_key(group_id))
            user_count = await cls._read_daily_count(cls._user_key(group_id, user_id))
        else:
            group_count = cls._group_counts.get(group_id, 0)
            user_count = cls._user_counts.get((group_id, user_id), 0)

        if group_count >= settings.GROUP_DAILY_GROUP_CAP:
            return GroupPolicyDecision(
                allowed=False,
                reason=t(lang, "group.group_cap"),
            )

        if user_count >= settings.GROUP_DAILY_USER_CAP:
            return GroupPolicyDecision(
                allowed=False,
                reason=t(lang, "group.user_cap"),
            )

        return cls.check_cooldown(group_id=group_id, user_id=user_id, lang=lang)

    @classmethod
    async def record_usage(cls, *, group_id: int, user_id: int) -> None:
        cls._reset_transient_if_needed()
        now = datetime.now(timezone.utc)
        user_key = (group_id, user_id)

        ttl = cls._seconds_until_midnight_utc()
        redis = await cls._get_redis()
        if redis is not None:
            try:
                pipe = redis.pipeline()
                gkey = cls._group_key(group_id)
                ukey = cls._user_key(group_id, user_id)
                pipe.incr(gkey)
                pipe.expire(gkey, ttl)
                pipe.incr(ukey)
                pipe.expire(ukey, ttl)
                await pipe.execute()
            except Exception as exc:
                logger.warning(
                    "GroupPolicy redis INCR failed group_id=%s user_id=%s error=%s",
                    group_id,
                    user_id,
                    exc,
                )
                cls._group_counts[group_id] = cls._group_counts.get(group_id, 0) + 1
                cls._user_counts[user_key] = cls._user_counts.get(user_key, 0) + 1
        else:
            cls._group_counts[group_id] = cls._group_counts.get(group_id, 0) + 1
            cls._user_counts[user_key] = cls._user_counts.get(user_key, 0) + 1

        cls._last_user_message_at[user_key] = now

    @classmethod
    def record_cooldown(cls, *, group_id: int, user_id: int) -> None:
        cls._reset_transient_if_needed()
        cls._last_user_message_at[(group_id, user_id)] = datetime.now(timezone.utc)
