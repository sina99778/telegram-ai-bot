"""
app/core/premium_emoji.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Optional Telegram custom (premium/animated) emoji rendering.

Telegram only lets a bot render custom emoji when the **bot owner has
Telegram Premium**. So this is OFF by default and fully graceful:

* When disabled (or a slot has no id) → text is returned unchanged (plain
  emoji). It can never break a message.
* When enabled and a slot's ``custom_emoji_id`` is set, the matching plain
  emoji is wrapped in ``<tg-emoji emoji-id="…">😀</tg-emoji>``. Non-premium
  viewers (and forwards) still see the plain fallback emoji inside the tag.

IMPORTANT: callers that send a premiumized string should keep a plain
fallback and retry with it on a Telegram error, in case the owner does not
actually have Premium (Telegram rejects the custom-emoji entity then).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.config.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

# RuntimeConfig text slot → the plain emoji it customises.
SLOTS: dict[str, str] = {
    "emoji_crown": "👑",
    "emoji_coin": "🪙",
    "emoji_spark": "✨",
    "emoji_gem": "💎",
    "emoji_fire": "🔥",
}


def premiumize(text: str, mapping: dict[str, str]) -> str:
    """Wrap each mapped plain emoji in a <tg-emoji> tag. Pure & idempotent-safe
    for a single pass (we only wrap bare emojis, never re-wrap)."""
    if not text or not mapping:
        return text
    for emoji, emoji_id in mapping.items():
        if not emoji_id:
            continue
        wrapped = f'<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji>'
        text = text.replace(emoji, wrapped)
    return text


async def load_mapping(session: AsyncSession) -> dict[str, str]:
    """Return {plain_emoji: custom_emoji_id} for configured slots, or {} when
    the feature is off / nothing configured."""
    try:
        if await RuntimeConfig.get_int(session, "premium_emoji_enabled") != 1:
            return {}
        mapping: dict[str, str] = {}
        for slot, emoji in SLOTS.items():
            emoji_id = (await RuntimeConfig.get_text(session, slot) or "").strip()
            if emoji_id:
                mapping[emoji] = emoji_id
        return mapping
    except Exception as exc:  # never let cosmetics break a message
        logger.warning("premium emoji load failed: %s", exc)
        return {}


async def decorate(session: AsyncSession, text: str) -> str:
    """Convenience: load the mapping and premiumize *text* in one call."""
    return premiumize(text, await load_mapping(session))
