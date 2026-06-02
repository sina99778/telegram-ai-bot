import pytest

from app.core import premium_emoji
from app.services.config.runtime_config import RuntimeConfig


@pytest.fixture(autouse=True)
def _clear_cache():
    RuntimeConfig.clear_cache()
    yield
    RuntimeConfig.clear_cache()


def test_premiumize_noop_without_mapping():
    text = "👑 VIP · 🪙 wallet"
    assert premium_emoji.premiumize(text, {}) == text
    assert premium_emoji.premiumize(text, None) == text


def test_premiumize_wraps_configured_emojis_only():
    text = "👑 VIP · 🪙 wallet · ✨"
    out = premium_emoji.premiumize(text, {"👑": "555", "🪙": "777"})
    assert '<tg-emoji emoji-id="555">👑</tg-emoji>' in out
    assert '<tg-emoji emoji-id="777">🪙</tg-emoji>' in out
    assert "✨" in out and "<tg-emoji emoji-id=\"\">✨" not in out  # ✨ untouched (not configured)


def test_premiumize_skips_empty_ids():
    text = "👑"
    assert premium_emoji.premiumize(text, {"👑": ""}) == "👑"


@pytest.mark.asyncio
async def test_load_mapping_disabled_by_default(db_session):
    # premium_emoji_enabled defaults to 0 → no mapping, decorate is a no-op.
    assert await premium_emoji.load_mapping(db_session) == {}
    assert await premium_emoji.decorate(db_session, "👑 hi") == "👑 hi"


@pytest.mark.asyncio
async def test_load_mapping_when_enabled_with_ids(db_session):
    await RuntimeConfig.set_int(db_session, "premium_emoji_enabled", 1)
    await RuntimeConfig.set_text(db_session, "emoji_crown", "12345")
    mapping = await premium_emoji.load_mapping(db_session)
    assert mapping == {"👑": "12345"}
    decorated = await premium_emoji.decorate(db_session, "👑 VIP")
    assert decorated == '<tg-emoji emoji-id="12345">👑</tg-emoji> VIP'
