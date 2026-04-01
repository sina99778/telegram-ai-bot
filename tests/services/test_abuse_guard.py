from __future__ import annotations

from app.services.security.abuse_guard import AbuseGuardService


def setup_function():
    AbuseGuardService._events = {}
    AbuseGuardService._failures = {}
    AbuseGuardService._temp_blocks = {}


def test_private_chat_throttle_blocks_burst():
    user_id = 123
    last_decision = None
    for _ in range(6):
        last_decision = AbuseGuardService.check_private_chat(user_id=user_id, lang="en")
    assert last_decision is not None
    assert last_decision.allowed is True

    blocked = AbuseGuardService.check_private_chat(user_id=user_id, lang="en")
    assert blocked.allowed is False


def test_repeated_failures_trigger_temp_block():
    user_id = 456
    for _ in range(5):
        AbuseGuardService.record_failure(subject="image", subject_id=user_id)

    decision = AbuseGuardService.check_image(user_id=user_id, lang="en")
    assert decision.allowed is False
