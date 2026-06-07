"""Regression tests for Gemini content building.

The chat used to "freeze" (and need /new) once a conversation grew past the
summarization threshold: the injected summary (role="system") was turned into a
`model` turn at the FRONT of the request, so Gemini rejected it (the first turn
must be `user`). These tests pin the normalization that fixes it.
"""

from __future__ import annotations

from app.services.ai.antigravity import _build_gemini_contents
from app.services.ai.provider import AIMessage


def _roles(contents):
    return [c.role for c in contents]


def _text(content):
    return " ".join(p.text for p in content.parts if getattr(p, "text", None))


def test_system_summary_is_pulled_into_system_instruction_not_a_turn():
    messages = [
        AIMessage(role="system", content="summary of earlier chat"),
        AIMessage(role="user", content="hello"),
        AIMessage(role="model", content="hi"),
        AIMessage(role="user", content="how are you?"),
    ]
    contents, extra_system = _build_gemini_contents(messages)
    # summary must NOT become a turn …
    assert "summary of earlier chat" in extra_system
    # … and the first turn must be a user turn.
    assert _roles(contents)[0] == "user"
    assert _roles(contents)[-1] == "user"


def test_leading_model_turns_are_dropped():
    # Happens when the sliding window trims the oldest user message.
    messages = [
        AIMessage(role="model", content="orphan model 1"),
        AIMessage(role="model", content="orphan model 2"),
        AIMessage(role="user", content="real question"),
    ]
    contents, _ = _build_gemini_contents(messages)
    assert _roles(contents) == ["user"]
    assert "real question" in _text(contents[0])


def test_consecutive_same_role_turns_merge_to_alternate():
    messages = [
        AIMessage(role="user", content="part 1"),
        AIMessage(role="user", content="part 2"),
        AIMessage(role="model", content="reply"),
        AIMessage(role="user", content="final"),
    ]
    contents, _ = _build_gemini_contents(messages)
    # strict alternation, starting + ending with user
    assert _roles(contents) == ["user", "model", "user"]
    assert "part 1" in _text(contents[0]) and "part 2" in _text(contents[0])


def test_top_level_image_attaches_to_last_user_turn():
    messages = [
        AIMessage(role="user", content="look at this"),
    ]
    contents, _ = _build_gemini_contents(messages, image_bytes=b"\xff\xd8\xff")
    # the user turn should now carry an inline image part + the text part
    assert _roles(contents) == ["user"]
    assert len(contents[0].parts) == 2


def test_quota_error_is_detected_and_not_retried():
    from app.services.ai.antigravity import (
        QuotaExhaustedError,
        _is_quota_error,
        _should_retry_gemini_error,
    )

    real = Exception(
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
        "'Your prepayment credits are depleted.', 'status': 'RESOURCE_EXHAUSTED'}}"
    )
    assert _is_quota_error(real) is True
    # quota / billing depletion is persistent → must NOT be retried
    assert _should_retry_gemini_error(real) is False
    assert _should_retry_gemini_error(QuotaExhaustedError("x")) is False
    # a generic transient error is still retried
    assert _should_retry_gemini_error(ConnectionError("reset")) is True


def test_normal_alternating_history_is_unchanged_in_shape():
    messages = [
        AIMessage(role="user", content="u1"),
        AIMessage(role="model", content="m1"),
        AIMessage(role="user", content="u2"),
    ]
    contents, extra_system = _build_gemini_contents(messages)
    assert _roles(contents) == ["user", "model", "user"]
    assert extra_system == ""
