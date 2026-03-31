from __future__ import annotations

from app.core.config import settings
from app.services.chat.group_policy import GroupPolicyService


def setup_function():
    GroupPolicyService._day_marker = None
    GroupPolicyService._group_counts = {}
    GroupPolicyService._user_counts = {}
    GroupPolicyService._last_user_message_at = {}


def test_group_policy_rejects_overlong_prompt():
    decision = GroupPolicyService.evaluate(
        group_id=100,
        user_id=200,
        prompt="x" * (settings.GROUP_MAX_PROMPT_LENGTH + 1),
    )

    assert decision.allowed is False
    assert "limited" in decision.reason.lower()


def test_group_policy_enforces_user_limit():
    for _ in range(settings.GROUP_DAILY_USER_CAP):
        GroupPolicyService.record_usage(group_id=100, user_id=200)

    decision = GroupPolicyService.evaluate(group_id=100, user_id=200, prompt="hello")

    assert decision.allowed is False
    assert "daily ai limit" in decision.reason.lower()
