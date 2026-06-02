"""
app/bot/keyboards/styling.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Button colour (``style``) + premium icon (``icon_custom_emoji_id``) styling.

Both fields arrived in **Bot API 9.4** and are supported by **aiogram ≥ 3.26**.
``style`` tints a button (``primary``=blue, ``success``=green, ``danger``=red);
``icon_custom_emoji_id`` puts an animated/custom premium emoji icon on it.

This module styles **every** keyboard from two angles, so we never have to touch
hundreds of build sites:

* :func:`colorize_inline_markup` / :func:`colorize_reply_markup` mutate a finished
  markup in place. They are **idempotent** (a button that already has a ``style``
  is left alone) so it is safe to run a markup through them more than once.
* :func:`install_global_coloring` monkeypatches ``InlineKeyboardBuilder.as_markup``
  so builder-made keyboards are coloured automatically.
* The ``markup()`` helper and the few hand-built markups call the colorizer too.

Premium icons are **opt-in**: they only apply when ``PREMIUM_EMOJI_ENABLED`` is
true *and* the matching ``CUSTOM_EMOJI_*`` id is configured. When off, nothing
changes (buttons keep their plain emoji text). Old Telegram clients simply
ignore ``style`` and render the plain button — it can never break a send.
"""

from __future__ import annotations

import re

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

# Leading whitespace + emoji (covers every emoji used in our button labels):
# the main emoji plane, dingbats/misc-symbols, stars/arrows, variation selector,
# ZWJ and keycap combiner.
_LEADING_EMOJI = re.compile(
    "^[\\s"
    "\U0001F000-\U0001FAFF"  # main emoji plane (faces, objects, flags, 🪙 🔥 …)
    "☀-➿"          # misc symbols & dingbats (✨ ✅ ✏ …)
    "⬀-⯿"          # stars & extra arrows (⭐ …)
    "←-⇿"          # arrows (⬅ ➡ …)
    "️‍⃣"     # variation selector, ZWJ, keycap combiner
    "]+"
)


def strip_leading_emoji(text: str) -> str:
    """Return *text* with any leading emoji/whitespace removed. Used both for
    premium-icon extraction and for emoji-agnostic menu routing."""
    return _LEADING_EMOJI.sub("", text or "").strip()


# callback_data token → colour (danger wins ties). We split the callback on
# :/_/-/. and match whole tokens, so "toggle_payg" is NOT mistaken for a
# payment ("pay" ≠ "payg") while "wallet:buy_normal" still reads as a purchase.
_TOKEN_SPLIT = re.compile(r"[:_\-.]+")
_DANGER = frozenset({
    "delete", "del", "ban", "cancel", "reject", "reset", "remove",
    "clear", "revoke", "deny", "block", "stop",
})
_SUCCESS = frozenset({
    "buy", "pay", "confirm", "renew", "gift", "approve", "redeem",
    "claim", "topup", "checkout", "unlock", "activate",
})


def _style_for_callback(callback_data: str) -> str:
    tokens = set(_TOKEN_SPLIT.split((callback_data or "").lower()))
    if tokens & _DANGER:
        return "danger"
    if tokens & _SUCCESS:
        return "success"
    return "primary"


def _premium_icon_map() -> dict[str, str]:
    """``{plain_emoji: custom_emoji_id}`` for configured slots, or ``{}`` when
    the feature is off / nothing configured.

    Gated by the ``premium_emoji_enabled`` runtime flag (read through
    :class:`RuntimeConfig`'s synchronous cache). The actual ids come from
    :class:`PremiumEmojiStore`'s synchronous cache, which the admin fills in from
    the panel by sending their own premium emoji. Works inside synchronous
    keyboard builders; returns ``{}`` when cold so it can never break a build."""
    from app.services.config.premium_emoji_store import PremiumEmojiStore
    from app.services.config.runtime_config import RuntimeConfig

    if RuntimeConfig.cached_int("premium_emoji_enabled") != 1:
        return {}
    return PremiumEmojiStore.cached_map()


def _norm_emoji(text: str) -> str:
    """Variation-selector-insensitive form, so '✏️' and '✏' compare equal."""
    return (text or "").replace("️", "")


def _apply_premium_icon(button) -> None:
    """If the button label starts with a mapped emoji, move it into
    ``icon_custom_emoji_id`` and drop it from the text. No-op when premium icons
    are disabled or the button already has an icon."""
    if getattr(button, "icon_custom_emoji_id", None):
        return
    mapping = _premium_icon_map()
    if not mapping:
        return
    lead = (button.text or "").lstrip()
    lead_norm = _norm_emoji(lead)
    for emoji, cid in mapping.items():
        if lead_norm.startswith(_norm_emoji(emoji)):
            button.icon_custom_emoji_id = cid
            # strip_leading_emoji drops the leading emoji regardless of any
            # variation selector, so the visible label is clean.
            button.text = strip_leading_emoji(lead) or button.text
            return


def colorize_inline_markup(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Colour + premium-icon every inline button (idempotent). Safe: inline
    buttons route by ``callback_data``, so changing the visible text never
    affects routing."""
    try:
        for row in markup.inline_keyboard:
            for button in row:
                if not getattr(button, "style", None):
                    button.style = (
                        _style_for_callback(button.callback_data)
                        if button.callback_data
                        else "primary"
                    )
                _apply_premium_icon(button)
    except Exception:  # cosmetics must never break a keyboard
        pass
    return markup


def _is_plain_text_reply_button(button) -> bool:
    """A reply button that just sends its text (no web_app / request_* action).
    We only restyle these — colouring the special-action buttons (e.g. the
    web_app "Open App" opener) is avoided so a critical menu can never fail to
    send if a client/server is picky about styling those."""
    special = (
        "web_app", "request_users", "request_user", "request_chat",
        "request_contact", "request_location", "request_poll",
    )
    return not any(getattr(button, attr, None) for attr in special)


def colorize_reply_markup(markup: ReplyKeyboardMarkup) -> ReplyKeyboardMarkup:
    """Colour + premium-icon plain-text reply-keyboard buttons (idempotent).

    NOTE: reply buttons route by the **text** the user sends, so stripping an
    emoji here can change that text. Menu routing is made emoji-agnostic (see
    ``app/bot/handlers/menu.py::_labels``) precisely so this stays safe."""
    try:
        for row in markup.keyboard:
            for button in row:
                if not _is_plain_text_reply_button(button):
                    continue
                if not getattr(button, "style", None):
                    button.style = "primary"
                _apply_premium_icon(button)
    except Exception:
        pass
    return markup


def install_global_coloring() -> None:
    """Monkeypatch ``InlineKeyboardBuilder.as_markup`` so every builder-made
    inline keyboard is coloured. Idempotent — safe to call more than once."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    if getattr(InlineKeyboardBuilder, "_coloring_installed", False):
        return
    _orig_as_markup = InlineKeyboardBuilder.as_markup

    def _patched_as_markup(self, *args, **kwargs):
        return colorize_inline_markup(_orig_as_markup(self, *args, **kwargs))

    InlineKeyboardBuilder.as_markup = _patched_as_markup
    InlineKeyboardBuilder._coloring_installed = True
