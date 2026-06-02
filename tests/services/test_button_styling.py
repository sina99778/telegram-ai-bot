"""Tests for Bot API 9.4 button styling: colour (`style`) + premium icons
(`icon_custom_emoji_id`), plus the emoji-agnostic menu routing that keeps the
reply keyboard working when premium icons strip a label's emoji."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.config import settings
from app.bot.keyboards.styling import (
    colorize_inline_markup,
    colorize_reply_markup,
    install_global_coloring,
    strip_leading_emoji,
)


def _inline(*buttons):
    return InlineKeyboardMarkup(inline_keyboard=[[b] for b in buttons])


def test_style_heuristic_by_callback():
    mk = colorize_inline_markup(
        _inline(
            InlineKeyboardButton(text="Buy", callback_data="wallet:buy_normal"),
            InlineKeyboardButton(text="Delete", callback_data="delete_user"),
            InlineKeyboardButton(text="Cancel", callback_data="cancel_action"),
            InlineKeyboardButton(text="Open", callback_data="vip:open"),
        )
    )
    styles = [row[0].style for row in mk.inline_keyboard]
    assert styles == ["success", "danger", "danger", "primary"]


def test_payg_toggle_is_not_mistaken_for_payment():
    # "toggle_payg" contains the substring "pay" but is a settings toggle.
    mk = colorize_inline_markup(_inline(InlineKeyboardButton(text="PAYG", callback_data="toggle_payg")))
    assert mk.inline_keyboard[0][0].style == "primary"


def test_existing_style_is_preserved():
    btn = InlineKeyboardButton(text="X", callback_data="delete_x", style="success")
    colorize_inline_markup(_inline(btn))
    assert btn.style == "success"  # not overwritten to danger


def test_premium_icons_off_by_default_leaves_text(monkeypatch):
    from app.services.config.premium_emoji_store import PremiumEmojiStore
    from app.services.config.runtime_config import RuntimeConfig

    RuntimeConfig.clear_cache()
    PremiumEmojiStore.clear_cache()
    monkeypatch.setattr(settings, "PREMIUM_EMOJI_ENABLED", False)
    btn = InlineKeyboardButton(text="🪙 Wallet", callback_data="wallet:open")
    colorize_inline_markup(_inline(btn))
    assert btn.text == "🪙 Wallet"
    assert btn.icon_custom_emoji_id is None


def test_premium_icons_on_moves_emoji_to_icon(monkeypatch):
    from app.services.config.premium_emoji_store import PremiumEmojiStore
    from app.services.config.runtime_config import RuntimeConfig

    RuntimeConfig.clear_cache()
    # enabled flag falls back to env default (True) when the cache is clear;
    # the id comes from the store's synchronous cache.
    monkeypatch.setattr(settings, "PREMIUM_EMOJI_ENABLED", True)
    PremiumEmojiStore._cache = {"🪙": "5301234567890123456"}
    btn = InlineKeyboardButton(text="🪙 Wallet", callback_data="wallet:open")
    colorize_inline_markup(_inline(btn))
    assert btn.icon_custom_emoji_id == "5301234567890123456"
    assert btn.text == "Wallet"  # emoji stripped from the label
    RuntimeConfig.clear_cache()
    PremiumEmojiStore.clear_cache()


def test_reply_buttons_get_colored():
    mk = colorize_reply_markup(
        ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🪙 Wallet"), KeyboardButton(text="👑 VIP")]])
    )
    assert all(b.style == "primary" for row in mk.keyboard for b in row)


def test_install_global_coloring_patches_builder():
    install_global_coloring()
    install_global_coloring()  # idempotent — second call is a no-op
    builder = InlineKeyboardBuilder()
    builder.button(text="Confirm", callback_data="confirm_pay")
    mk = builder.as_markup()
    assert mk.inline_keyboard[0][0].style == "success"


def test_strip_leading_emoji_handles_all_menu_emojis():
    cases = {
        "💬 Chat": "Chat",
        "🔎 Online Search": "Online Search",
        "✏️ Edit Photo": "Edit Photo",
        "🪙 Wallet": "Wallet",
        "👑 VIP": "VIP",
        "🚀 Open App": "Open App",
        "⭐ Star": "Star",
        "Plain text": "Plain text",
    }
    for raw, expected in cases.items():
        assert strip_leading_emoji(raw) == expected


def test_menu_labels_are_emoji_agnostic():
    # The menu router must match a button whether or not its emoji was stripped.
    from app.bot.handlers.menu import _labels

    wallet_labels = _labels("buttons.wallet")
    # both the emoji'd label and the stripped one are present
    assert any(lbl.startswith("🪙") for lbl in wallet_labels)
    assert "Wallet" in wallet_labels
