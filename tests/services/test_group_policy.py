from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.chat.group_policy import GroupPolicyService


def setup_function():
    GroupPolicyService._day_marker = None
    GroupPolicyService._group_counts = {}
    GroupPolicyService._user_counts = {}
    GroupPolicyService._last_user_message_at = {}
    GroupPolicyService._handled_messages = {}
    # Force the in-memory fallback path for deterministic tests
    GroupPolicyService._redis = None
    GroupPolicyService._redis_disabled = True


def teardown_function():
    GroupPolicyService._redis_disabled = False


@pytest.mark.asyncio
async def test_group_policy_rejects_overlong_prompt():
    decision = await GroupPolicyService.evaluate(
        group_id=100,
        user_id=200,
        prompt="x" * (settings.GROUP_MAX_PROMPT_LENGTH + 1),
    )

    assert decision.allowed is False
    assert "limited" in decision.reason.lower()


@pytest.mark.asyncio
async def test_group_policy_enforces_user_limit():
    for _ in range(settings.GROUP_DAILY_USER_CAP):
        await GroupPolicyService.record_usage(group_id=100, user_id=200)

    decision = await GroupPolicyService.evaluate(group_id=100, user_id=200, prompt="hello")

    assert decision.allowed is False
    assert "daily ai limit" in decision.reason.lower()


def test_group_policy_claim_message_deduplicates_group_updates():
    assert GroupPolicyService.claim_message(group_id=100, message_id=300) is True
    assert GroupPolicyService.claim_message(group_id=100, message_id=300) is False


def test_group_policy_check_cooldown_blocks_recent_user_activity():
    GroupPolicyService.record_cooldown(group_id=100, user_id=200)

    decision = GroupPolicyService.check_cooldown(group_id=100, user_id=200)

    assert decision.allowed is False
    assert "wait" in decision.reason.lower()
