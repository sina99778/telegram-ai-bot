"""
app/bot/middlewares/premium_icon_fallback.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bot-wide safety net for premium-emoji button icons.

``icon_custom_emoji_id`` (Bot API 9.4) only renders if the emoji is actually
usable by the bot. If an admin configures an id the bot can't emit, Telegram
rejects the WHOLE send/edit with HTTP 400 — which would otherwise take down
EVERY keyboard in the bot. This request middleware catches that specific 400
and retries the request once with the icons stripped, so a bad id degrades to a
plain (still-coloured) button instead of breaking the message.
"""

from __future__ import annotations

import logging

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)


def _strip_icons(markup) -> bool:
    """Remove icon_custom_emoji_id from every button in a markup (in place).
    Returns True if anything was changed."""
    if markup is None:
        return False
    rows = getattr(markup, "inline_keyboard", None)
    if rows is None:
        rows = getattr(markup, "keyboard", None)
    if not rows:
        return False
    changed = False
    for row in rows:
        for button in row:
            if getattr(button, "icon_custom_emoji_id", None):
                button.icon_custom_emoji_id = None
                changed = True
    return changed


class PremiumIconFallbackMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            if "emoji" in message and _strip_icons(getattr(method, "reply_markup", None)):
                logger.warning("Retrying send without premium icons after Telegram rejected them: %s", exc)
                return await make_request(bot, method)
            raise
