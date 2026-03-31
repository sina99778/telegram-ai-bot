from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.core.config import settings


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

    @classmethod
    def _reset_if_needed(cls) -> None:
        today = datetime.now(timezone.utc).date()
        if cls._day_marker != today:
            cls._day_marker = today
            cls._group_counts = {}
            cls._user_counts = {}
            cls._last_user_message_at = {}

    @classmethod
    def evaluate(cls, *, group_id: int, user_id: int, prompt: str) -> GroupPolicyDecision:
        cls._reset_if_needed()
        now = datetime.now(timezone.utc)
        user_key = (group_id, user_id)

        if len(prompt) > settings.GROUP_MAX_PROMPT_LENGTH:
            return GroupPolicyDecision(
                allowed=False,
                reason=f"Group prompts are limited to {settings.GROUP_MAX_PROMPT_LENGTH} characters.",
            )

        group_count = cls._group_counts.get(group_id, 0)
        if group_count >= settings.GROUP_DAILY_GROUP_CAP:
            return GroupPolicyDecision(
                allowed=False,
                reason="This group has reached its daily AI usage limit.",
            )

        user_count = cls._user_counts.get(user_key, 0)
        if user_count >= settings.GROUP_DAILY_USER_CAP:
            return GroupPolicyDecision(
                allowed=False,
                reason="You reached your daily AI limit in this group.",
            )

        last_seen = cls._last_user_message_at.get(user_key)
        if last_seen and now - last_seen < timedelta(seconds=settings.GROUP_USER_COOLDOWN_SECONDS):
            remaining = settings.GROUP_USER_COOLDOWN_SECONDS - int((now - last_seen).total_seconds())
            return GroupPolicyDecision(
                allowed=False,
                reason=f"Please wait {remaining} more seconds before asking again in this group.",
            )

        return GroupPolicyDecision(allowed=True)

    @classmethod
    def record_usage(cls, *, group_id: int, user_id: int) -> None:
        cls._reset_if_needed()
        now = datetime.now(timezone.utc)
        user_key = (group_id, user_id)
        cls._group_counts[group_id] = cls._group_counts.get(group_id, 0) + 1
        cls._user_counts[user_key] = cls._user_counts.get(user_key, 0) + 1
        cls._last_user_message_at[user_key] = now
