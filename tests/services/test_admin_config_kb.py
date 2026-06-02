"""Keyboard wiring tests for the admin runtime-config panel."""

from __future__ import annotations

import pytest

from app.bot.keyboards.admin_kb import (
    CONFIG_SECTIONS,
    get_admin_config_kb,
    get_admin_config_section_kb,
    get_admin_emoji_kb,
    get_admin_main_kb,
)
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


def test_search_token_keeps_callback_data_under_64_bytes():
    """Telegram rejects callback_data > 64 bytes. A long or Persian search
    term embedded in admin user-list callbacks must stay within budget."""
    from app.bot.keyboards.admin_kb import _safe_search_token

    for term in ["a" * 80, "محمدرضا حسینی نژاد بزرگ", "user:name:with:colons", "", None]:
        token = _safe_search_token(term)
        # worst-case (longest prefix) callback we build with a search token
        cb = f"admin:user:add_normal:1234567890:page:999:search:{token}"
        assert len(cb.encode("utf-8")) <= 64, (term, len(cb.encode("utf-8")))
        assert ":" not in token  # delimiter must not leak into the token
        assert token.encode("utf-8").decode("utf-8") == token  # no half-truncated char


def test_user_management_kb_callbacks_are_byte_safe():
    from types import SimpleNamespace
    from app.bot.keyboards.admin_kb import get_user_manage_kb

    user = SimpleNamespace(
        telegram_id=1234567890, is_banned=False, has_active_vip=False,
        username=None, first_name="x", normal_credits=0, vip_credits=0,
    )
    markup = get_user_manage_kb(user, "fa", page=999, search="محمدرضا حسینی نژاد بزرگ")
    for btn in _flatten(markup):
        if btn.callback_data:
            assert len(btn.callback_data.encode("utf-8")) <= 64, btn.callback_data


def test_admin_main_kb_has_config_button():
    buttons = _flatten(get_admin_main_kb("en"))
    assert any(b.callback_data == "admin:config" for b in buttons)


def test_config_home_shows_section_buttons():
    """The settings home is a set of section buttons (not one giant list)."""
    buttons = _flatten(get_admin_config_kb("en"))
    cbs = {b.callback_data for b in buttons}
    assert "admin:config:cat:pricing" in cbs
    assert "admin:config:cat:limits" in cbs
    assert "admin:config:cat:context" in cbs
    assert "admin:config:cat:payments" in cbs
    assert "admin:emoji" in cbs          # premium-emoji manager entry
    assert "admin:main" in cbs           # home


def test_section_kb_one_button_per_key_with_value_and_set_callback():
    snapshot = [
        {"key": "free_daily_image", "value": 2, "is_override": False},
        {"key": "search_daily_free", "value": 1, "is_override": True},
    ]
    buttons = _flatten(get_admin_config_section_kb("limits", snapshot, "en"))
    set_buttons = [b for b in buttons if (b.callback_data or "").startswith("admin:config:set:")]

    assert {b.callback_data for b in set_buttons} == {
        "admin:config:set:free_daily_image",
        "admin:config:set:search_daily_free",
    }
    labels = {b.text for b in set_buttons}
    assert any("free_daily_image = 2" == lbl for lbl in labels)
    assert any(lbl.startswith("search_daily_free = 1") and "★" in lbl for lbl in labels)
    # A section goes back to the config home, and home to the panel.
    assert any(b.callback_data == "admin:config" for b in buttons)
    assert any(b.callback_data == "admin:main" for b in buttons)


def test_payments_section_has_text_buttons_and_fetch_rate():
    """Card details are editable via buttons; the rate fetch lives here too."""
    snapshot = [{"key": "usd_toman_rate", "value": 0, "is_override": False}]
    text_items = [
        {"key": "card_number", "value": "6037-xxxx"},
        {"key": "card_holder", "value": ""},
    ]
    buttons = _flatten(get_admin_config_section_kb("payments", snapshot, "en", text_items=text_items))
    settext = [b for b in buttons if (b.callback_data or "").startswith("admin:config:settext:")]
    assert {b.callback_data for b in settext} == {
        "admin:config:settext:card_number",
        "admin:config:settext:card_holder",
    }
    labels = {b.text for b in settext}
    assert any("card_number" in lbl and "6037-xxxx" in lbl for lbl in labels)
    assert any("card_holder" in lbl and "—" in lbl for lbl in labels)
    assert any(b.callback_data == "admin:config:fetchrate" for b in buttons)


def test_emoji_kb_lists_registry_with_toggle():
    from app.services.config.premium_emoji_store import EMOJI_REGISTRY

    buttons = _flatten(get_admin_emoji_kb("en", enabled=False, configured_slugs={"crown"}))
    cbs = [b.callback_data for b in buttons]
    assert "admin:emoji:toggle" in cbs
    slug_cbs = [c for c in cbs if (c or "").startswith("admin:emoji:s:")]
    assert len(slug_cbs) == len(EMOJI_REGISTRY)
    # the configured one is marked ✅, others ➕
    crown_btn = next(b for b in buttons if b.callback_data == "admin:emoji:s:crown")
    assert "✅" in crown_btn.text
    # every slug callback stays well under Telegram's 64-byte cap
    for c in slug_cbs:
        assert len(c.encode("utf-8")) <= 64


def test_topup_keyboard_routes_to_correct_buy_screen():
    from app.bot.keyboards.inline import get_topup_keyboard
    from app.core.enums import WalletType

    normal = _flatten(get_topup_keyboard("en", WalletType.NORMAL))
    vip = _flatten(get_topup_keyboard("en", WalletType.VIP))
    assert any(b.callback_data == "wallet:buy_normal" for b in normal)
    assert any(b.callback_data == "wallet:buy_vip" for b in vip)
    # both also offer the general wallet entry, and stay byte-safe
    for kb in (normal, vip):
        assert any(b.callback_data == "wallet:open" for b in kb)
        for b in kb:
            assert len((b.callback_data or "").encode("utf-8")) <= 64


def test_failure_markup_only_on_billing_errors():
    from types import SimpleNamespace
    from app.bot.handlers.chat import _failure_markup
    from app.core.enums import WalletType

    insufficient = SimpleNamespace(error_message="insufficient_funds", wallet_type=WalletType.NORMAL)
    safety = SimpleNamespace(error_message="safety_blocked", wallet_type=None)
    assert _failure_markup(insufficient, "en") is not None
    assert _failure_markup(safety, "en") is None


def test_config_set_callback_roundtrips_through_registry():
    """Every key embedded in a section's set-callback must parse back to a valid
    registry key, across all sections."""
    snapshot = [{"key": k, "value": 0, "is_override": False} for k in RuntimeConfig.REGISTRY]
    for section in CONFIG_SECTIONS:
        buttons = _flatten(get_admin_config_section_kb(section, snapshot, "en"))
        for b in buttons:
            cb = b.callback_data or ""
            if cb.startswith("admin:config:set:"):
                key = cb.split(":", 3)[3]
                assert RuntimeConfig.is_valid_key(key)


def test_every_registry_key_appears_in_some_section():
    """No runtime-config key should be orphaned out of the sectioned UI."""
    sectioned = {k for keys in CONFIG_SECTIONS.values() for k in keys}
    # premium_emoji_enabled is managed in the dedicated emoji screen, not a section.
    expected = set(RuntimeConfig.REGISTRY) - {"premium_emoji_enabled"}
    missing = expected - sectioned
    assert not missing, f"keys missing from CONFIG_SECTIONS: {missing}"
