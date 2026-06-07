"""Tests for the admin-managed forced channel-join feature."""

from __future__ import annotations

import pytest

from app.services.config.runtime_config import RuntimeConfig


@pytest.fixture(autouse=True)
def _clear_cache():
    RuntimeConfig.clear_cache()
    yield
    RuntimeConfig.clear_cache()


def _flatten(markup):
    return [b for row in markup.inline_keyboard for b in row]


def test_normalize_channel_variants():
    from app.bot.handlers.admin import _normalize_channel

    assert _normalize_channel("mychannel") == "@mychannel"
    assert _normalize_channel("@mychannel") == "@mychannel"
    assert _normalize_channel("https://t.me/mychannel") == "@mychannel"
    assert _normalize_channel("t.me/mychannel/") == "@mychannel"
    assert _normalize_channel("t.me/mychannel?start=x") == "@mychannel"  # path/query dropped
    assert _normalize_channel("-1001234567890") == "-1001234567890"  # numeric id kept
    assert _normalize_channel("   ") == ""
    # Private invite links can't be used for membership checks → rejected.
    assert _normalize_channel("https://t.me/+AbCdEf123") == ""
    assert _normalize_channel("t.me/joinchat/XXXX") == ""


def test_is_valid_channel():
    from app.bot.handlers.admin import _is_valid_channel, _normalize_channel

    assert _is_valid_channel(_normalize_channel("mychannel")) is True
    assert _is_valid_channel(_normalize_channel("-1001234567890")) is True
    assert _is_valid_channel(_normalize_channel("https://t.me/+AbCdEf123")) is False  # ""
    assert _is_valid_channel("@a") is False  # too short
    assert _is_valid_channel("@1bad") is False  # must start with a letter


def test_join_kb_shows_clear_only_when_channel_set():
    from app.bot.keyboards.admin_kb import get_admin_join_kb

    without = {b.callback_data for b in _flatten(get_admin_join_kb("en", enabled=False, has_channel=False))}
    assert "admin:join:toggle" in without
    assert "admin:join:setchannel" in without
    assert "admin:join:clear" not in without  # nothing to clear

    with_ch = {b.callback_data for b in _flatten(get_admin_join_kb("en", enabled=True, has_channel=True))}
    assert "admin:join:clear" in with_ch


@pytest.mark.asyncio
async def test_middleware_reads_runtime_config(db_session):
    from app.bot.middlewares.forced_join import _resolve_config

    # Defaults: disabled.
    enabled, channel = await _resolve_config(db_session)
    assert enabled is False

    # Admin turns it on + sets a channel → middleware must see it.
    await RuntimeConfig.set_int(db_session, "forced_join_enabled", 1)
    await RuntimeConfig.set_text(db_session, "forced_join_channel", "@mychannel")
    enabled, channel = await _resolve_config(db_session)
    assert enabled is True
    assert channel == "@mychannel"


@pytest.mark.asyncio
async def test_resolve_config_falls_back_without_session():
    from app.bot.middlewares.forced_join import _resolve_config

    # No session → never raises, returns env-based defaults.
    enabled, channel = await _resolve_config(None)
    assert isinstance(enabled, bool)
    assert isinstance(channel, str)
