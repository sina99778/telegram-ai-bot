from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.i18n import t


@dataclass
class GuardDecision:
    allowed: bool
    reason: str | None = None


class AbuseGuardService:
    """Small in-memory anti-abuse guard for burst control and temporary blocks."""

    _events: dict[tuple[str, int], list[datetime]] = {}
    _failures: dict[tuple[str, int], list[datetime]] = {}
    _temp_blocks: dict[tuple[str, int], datetime] = {}

    @classmethod
    def _now(cls) -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _prune(cls) -> None:
        now = cls._now()
        max_window = max(
            settings.PRIVATE_MESSAGE_BURST_WINDOW_SECONDS,
            settings.SEARCH_COMMAND_COOLDOWN_SECONDS,
            settings.IMAGE_COMMAND_COOLDOWN_SECONDS,
            settings.ADMIN_ACTION_COOLDOWN_SECONDS,
            settings.ABUSE_FAILURE_WINDOW_SECONDS,
            settings.CALLBACK_COOLDOWN_SECONDS,
        )
        cutoff = now - timedelta(seconds=max_window)
        cls._events = {
            key: [stamp for stamp in stamps if stamp >= cutoff]
            for key, stamps in cls._events.items()
            if any(stamp >= cutoff for stamp in stamps)
        }
        failure_cutoff = now - timedelta(seconds=settings.ABUSE_FAILURE_WINDOW_SECONDS)
        cls._failures = {
            key: [stamp for stamp in stamps if stamp >= failure_cutoff]
            for key, stamps in cls._failures.items()
            if any(stamp >= failure_cutoff for stamp in stamps)
        }
        cls._temp_blocks = {
            key: blocked_until
            for key, blocked_until in cls._temp_blocks.items()
            if blocked_until > now
        }

    @classmethod
    def _check_temp_block(cls, *, subject: str, subject_id: int, lang: str) -> GuardDecision:
        cls._prune()
        blocked_until = cls._temp_blocks.get((subject, subject_id))
        if not blocked_until:
            return GuardDecision(allowed=True)
        remaining = max(1, int((blocked_until - cls._now()).total_seconds()))
        return GuardDecision(allowed=False, reason=t(lang, "abuse.temp_blocked", seconds=remaining))

    @classmethod
    def _hit_window(
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
        block_decision = cls._check_temp_block(subject=subject, subject_id=subject_id, lang=lang)
        if not block_decision.allowed:
            return block_decision

        cls._prune()
        now = cls._now()
        key = (subject, subject_id)
        stamps = cls._events.get(key, [])
        cutoff = now - timedelta(seconds=window_seconds)
        stamps = [stamp for stamp in stamps if stamp >= cutoff]
        if len(stamps) >= limit:
            kwargs = reason_kwargs or {}
            return GuardDecision(allowed=False, reason=t(lang, reason_key, **kwargs))
        stamps.append(now)
        cls._events[key] = stamps
        return GuardDecision(allowed=True)

    @classmethod
    def check_private_chat(cls, *, user_id: int, lang: str) -> GuardDecision:
        return cls._hit_window(
            subject="private_chat",
            subject_id=user_id,
            limit=settings.PRIVATE_MESSAGE_BURST_LIMIT,
            window_seconds=settings.PRIVATE_MESSAGE_BURST_WINDOW_SECONDS,
            lang=lang,
            reason_key="abuse.private_chat_rate_limited",
            reason_kwargs={"seconds": settings.PRIVATE_MESSAGE_BURST_WINDOW_SECONDS},
        )

    @classmethod
    def check_search(cls, *, scope_id: int, is_group: bool, lang: str) -> GuardDecision:
        return cls._hit_window(
            subject="group_search" if is_group else "user_search",
            subject_id=scope_id,
            limit=1,
            window_seconds=settings.SEARCH_COMMAND_COOLDOWN_SECONDS,
            lang=lang,
            reason_key="abuse.search_rate_limited",
            reason_kwargs={"seconds": settings.SEARCH_COMMAND_COOLDOWN_SECONDS},
        )

    @classmethod
    def check_image(cls, *, user_id: int, lang: str) -> GuardDecision:
        return cls._hit_window(
            subject="image",
            subject_id=user_id,
            limit=1,
            window_seconds=settings.IMAGE_COMMAND_COOLDOWN_SECONDS,
            lang=lang,
            reason_key="abuse.image_rate_limited",
            reason_kwargs={"seconds": settings.IMAGE_COMMAND_COOLDOWN_SECONDS},
        )

    @classmethod
    def check_callback(cls, *, user_id: int, lang: str) -> GuardDecision:
        return cls._hit_window(
            subject="callback",
            subject_id=user_id,
            limit=1,
            window_seconds=settings.CALLBACK_COOLDOWN_SECONDS,
            lang=lang,
            reason_key="abuse.callback_rate_limited",
            reason_kwargs={"seconds": settings.CALLBACK_COOLDOWN_SECONDS},
        )

    @classmethod
    def check_admin_action(cls, *, admin_id: int, action: str, lang: str) -> GuardDecision:
        return cls._hit_window(
            subject=f"admin:{action}",
            subject_id=admin_id,
            limit=1,
            window_seconds=settings.ADMIN_ACTION_COOLDOWN_SECONDS,
            lang=lang,
            reason_key="abuse.admin_rate_limited",
            reason_kwargs={"seconds": settings.ADMIN_ACTION_COOLDOWN_SECONDS},
        )

    @classmethod
    def enforce_prompt_length(cls, *, prompt: str, limit: int, lang: str) -> GuardDecision:
        if len(prompt) > limit:
            return GuardDecision(allowed=False, reason=t(lang, "abuse.prompt_too_long", limit=limit))
        return GuardDecision(allowed=True)

    @classmethod
    def record_failure(cls, *, subject: str, subject_id: int) -> None:
        cls._prune()
        now = cls._now()
        key = (subject, subject_id)
        stamps = cls._failures.get(key, [])
        cutoff = now - timedelta(seconds=settings.ABUSE_FAILURE_WINDOW_SECONDS)
        stamps = [stamp for stamp in stamps if stamp >= cutoff]
        stamps.append(now)
        cls._failures[key] = stamps
        if len(stamps) >= settings.ABUSE_FAILURE_THRESHOLD:
            cls._temp_blocks[key] = now + timedelta(seconds=settings.ABUSE_TEMP_BLOCK_SECONDS)
