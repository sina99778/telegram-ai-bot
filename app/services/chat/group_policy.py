from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.core.config import settings
from app.core.i18n import t


@dataclass
class GroupPolicyDecision:
    allowed: bool
    reason: str | None = None


class GroupPolicyService:
    """Centralized in-memory guardrails for group usage."""

    _day_marker: date | None = None
    _group_counts: dict[int, int] = {}
    _user_counts: dict[tuple[int, int], int] = {}
    _last_user_message_at: dict[tuple[int, int], datetime] = {}
    _handled_messages: dict[tuple[int, int], datetime] = {}
    _handled_ttl_seconds: int = 60

    @classmethod
    def _reset_if_needed(cls) -> None:
        today = datetime.now(timezone.utc).date()
        if cls._day_marker != today:
            cls._day_marker = today
            cls._group_counts = {}
            cls._user_counts = {}
            cls._last_user_message_at = {}
            cls._handled_messages = {}
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
        cls._reset_if_needed()
        key = (group_id, message_id)
        if key in cls._handled_messages:
            return False
        cls._handled_messages[key] = datetime.now(timezone.utc)
        return True

    @classmethod
    def check_cooldown(cls, *, group_id: int, user_id: int, lang: str = "en") -> GroupPolicyDecision:
        cls._reset_if_needed()
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
    def evaluate(cls, *, group_id: int, user_id: int, prompt: str, lang: str = "en") -> GroupPolicyDecision:
        cls._reset_if_needed()
        user_key = (group_id, user_id)

        if len(prompt) > settings.GROUP_MAX_PROMPT_LENGTH:
            return GroupPolicyDecision(
                allowed=False,
                reason=t(lang, "group.prompt_limit", limit=settings.GROUP_MAX_PROMPT_LENGTH),
            )

        group_count = cls._group_counts.get(group_id, 0)
        if group_count >= settings.GROUP_DAILY_GROUP_CAP:
            return GroupPolicyDecision(
                allowed=False,
                reason=t(lang, "group.group_cap"),
            )

        user_count = cls._user_counts.get(user_key, 0)
        if user_count >= settings.GROUP_DAILY_USER_CAP:
            return GroupPolicyDecision(
                allowed=False,
                reason=t(lang, "group.user_cap"),
            )

        return cls.check_cooldown(group_id=group_id, user_id=user_id, lang=lang)

    @classmethod
    def record_usage(cls, *, group_id: int, user_id: int) -> None:
        cls._reset_if_needed()
        now = datetime.now(timezone.utc)
        user_key = (group_id, user_id)
        cls._group_counts[group_id] = cls._group_counts.get(group_id, 0) + 1
        cls._user_counts[user_key] = cls._user_counts.get(user_key, 0) + 1
        cls._last_user_message_at[user_key] = now

    @classmethod
    def record_cooldown(cls, *, group_id: int, user_id: int) -> None:
        cls._reset_if_needed()
        cls._last_user_message_at[(group_id, user_id)] = datetime.now(timezone.utc)
