"""Tests for the inline-mode reply editing (_safe_edit_inline)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bot.handlers.inline import _clip, _safe_edit_inline


class FakeBot:
    def __init__(self):
        self.calls = []

    async def edit_message_text(self, **kwargs):
        self.calls.append(kwargs)


def _fake_chosen(bot):
    # _safe_edit_inline only reads .bot and .inline_message_id
    return SimpleNamespace(bot=bot, inline_message_id="imid-1")


def test_clip_only_truncates_when_too_long():
    assert _clip("short") == "short"                      # untouched — no stray ellipsis
    long = "x" * 5000
    out = _clip(long)
    assert len(out) <= 4096
    assert out.endswith("…")


@pytest.mark.asyncio
async def test_short_inline_reply_has_no_stray_ellipsis():
    bot = FakeBot()
    await _safe_edit_inline(_fake_chosen(bot), "the answer", prompt="hi", name="Sina")
    assert len(bot.calls) == 1
    text = bot.calls[0]["text"]
    assert "the answer" in text
    assert not text.endswith("...")
    assert not text.endswith("…")
    assert bot.calls[0]["inline_message_id"] == "imid-1"


@pytest.mark.asyncio
async def test_long_inline_reply_is_clipped_with_header_kept():
    bot = FakeBot()
    await _safe_edit_inline(_fake_chosen(bot), "y" * 6000, prompt="hello", name="Sina")
    text = bot.calls[0]["text"]
    assert len(text) <= 4096
    assert text.startswith("🗣 <b>Sina:</b> hello")
    assert text.endswith("…")


@pytest.mark.asyncio
async def test_user_input_is_escaped_in_header():
    bot = FakeBot()
    await _safe_edit_inline(_fake_chosen(bot), "ok", prompt="<script>", name="<b>Eve</b>")
    text = bot.calls[0]["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&lt;b&gt;Eve&lt;/b&gt;" in text
