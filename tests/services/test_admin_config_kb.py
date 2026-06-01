"""Keyboard wiring tests for the admin runtime-config panel."""

from __future__ import annotations

import pytest

from app.bot.keyboards.admin_kb import get_admin_config_kb, get_admin_main_kb
from app.core.i18n import t
from app.services.config.runtime_config import RuntimeConfig


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_config_i18n_strings_format_with_handler_kwargs(lang):
    """Regression: t() takes a positional param named `key`, so an i18n
    placeholder also named {key} (passed as key=...) raised TypeError and
    made the config buttons silently die. These calls mirror the handlers
    exactly and must not raise."""
    spec = RuntimeConfig.REGISTRY["search_daily_free"]
    # set_prompt (tap a key)
    t(lang, "admin.config.set_prompt", setting="search_daily_free",
      description=spec.description, value=2, default=2, min=spec.minimum, max=spec.maximum)
    # row (/config listing)
    t(lang, "admin.config.row", setting="search_daily_free", value=2,
      default=2, description=spec.description, star="")
    # unknown_key / out_of_range / saved (set flow)
    t(lang, "admin.config.unknown_key", setting="bogus")
    t(lang, "admin.config.out_of_range", setting="search_daily_free", min=0, max=1000)
    t(lang, "admin.config.saved", setting="search_daily_free", value=1, old=2)


def _flatten(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def _flatten(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def test_admin_main_kb_has_config_button():
    buttons = _flatten(get_admin_main_kb("en"))
    assert any(b.callback_data == "admin:config" for b in buttons)


def test_config_kb_one_button_per_key_with_value_and_set_callback():
    snapshot = [
        {"key": "free_daily_image", "value": 2, "is_override": False},
        {"key": "search_daily_free", "value": 1, "is_override": True},
    ]
    buttons = _flatten(get_admin_config_kb(snapshot, "en"))
    set_buttons = [b for b in buttons if (b.callback_data or "").startswith("admin:config:set:")]

    assert len(set_buttons) == 2
    assert {b.callback_data for b in set_buttons} == {
        "admin:config:set:free_daily_image",
        "admin:config:set:search_daily_free",
    }
    # Each button shows the live value; the overridden one is starred.
    labels = {b.text for b in set_buttons}
    assert any("free_daily_image = 2" == lbl for lbl in labels)
    assert any(lbl.startswith("search_daily_free = 1") and "★" in lbl for lbl in labels)

    # Navigation back to the panel is present.
    assert any(b.callback_data == "admin:main" for b in buttons)
    assert any(b.callback_data == "admin:config" for b in buttons)  # refresh


def test_config_set_callback_roundtrips_through_registry():
    """The key embedded in the callback must be parseable back to a valid key."""
    from app.services.config.runtime_config import RuntimeConfig

    snapshot = [{"key": k, "value": 0, "is_override": False} for k in RuntimeConfig.REGISTRY]
    buttons = _flatten(get_admin_config_kb(snapshot, "en"))
    for b in buttons:
        cb = b.callback_data or ""
        if cb.startswith("admin:config:set:"):
            key = cb.split(":", 3)[3]
            assert RuntimeConfig.is_valid_key(key)
