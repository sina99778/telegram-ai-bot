"""
app/services/config/premium_emoji_store.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Per-emoji premium (custom) emoji mapping, editable from the admin panel.

The admin sees the **complete list of emojis the bot uses** as buttons. Tapping
one and then *sending a message that contains their own premium emoji* lets the
bot read the ``custom_emoji_id`` straight out of the message entities — no
copy-pasting numeric ids. Each mapping is stored as its own ``bot_settings`` row
``emoji:<slug>`` → ``custom_emoji_id`` (the ``value`` column is only 255 chars,
so one row per emoji — not a single JSON blob).

Two consumers read the resulting ``{plain_emoji: custom_emoji_id}`` map:
* keyboard styling (button ``icon_custom_emoji_id``) — synchronously via
  :meth:`cached_map`;
* welcome-message decoration (``<tg-emoji>``) — asynchronously via
  :meth:`get_map`.

Both are gated by the ``premium_emoji_enabled`` runtime flag.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotSetting

logger = logging.getLogger(__name__)

_KEY_PREFIX = "emoji:"

# The complete set of emojis the bot uses in its UI, each with a stable ascii
# slug (used as the storage key) and a short human label for the admin list.
# Order here is the order shown in the admin panel.
EMOJI_REGISTRY: list[tuple[str, str, str]] = [
    ("crown", "👑", "Crown · VIP"),
    ("coin", "🪙", "Coin · Credits"),
    ("gem", "💎", "Gem · Pro"),
    ("spark", "✨", "Sparkles"),
    ("fire", "🔥", "Fire"),
    ("rocket", "🚀", "Rocket · Open App"),
    ("chat", "💬", "Chat"),
    ("search", "🔎", "Search"),
    ("image", "🖼", "Image"),
    ("pencil", "✏️", "Edit photo"),
    ("gift", "🎁", "Gift · Codes"),
    ("ticket", "🎟", "Redeem"),
    ("people", "👥", "Invite"),
    ("sos", "🆘", "Support"),
    ("book", "📘", "Guide"),
    ("globe", "🌐", "Language"),
    ("party", "🎉", "Daily reward"),
    ("brain", "🧠", "Memory"),
    ("books", "📚", "History"),
    ("card", "💳", "Checkout"),
    ("chart", "📊", "Stats"),
    ("megaphone", "📣", "Broadcast"),
    ("tools", "🛠", "Admin"),
    ("home", "🏠", "Home"),
]

_SLUG_TO_EMOJI: dict[str, str] = {slug: emoji for slug, emoji, _ in EMOJI_REGISTRY}
_SLUG_TO_LABEL: dict[str, str] = {slug: label for slug, _, label in EMOJI_REGISTRY}


def emoji_for_slug(slug: str) -> str | None:
    return _SLUG_TO_EMOJI.get(slug)


def label_for_slug(slug: str) -> str:
    return _SLUG_TO_LABEL.get(slug, slug)


def is_valid_slug(slug: str) -> bool:
    return slug in _SLUG_TO_EMOJI


class PremiumEmojiStore:
    # Synchronous snapshot of {plain_emoji: custom_emoji_id}, refreshed on every
    # async read/write and warmed at startup. None means "never loaded".
    _cache: dict[str, str] | None = None

    @classmethod
    def cached_map(cls) -> dict[str, str]:
        return dict(cls._cache) if cls._cache is not None else {}

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache = None

    @classmethod
    async def get_map(cls, session: AsyncSession) -> dict[str, str]:
        """Return ``{plain_emoji: custom_emoji_id}`` for every configured slot."""
        mapping: dict[str, str] = {}
        try:
            rows = (await session.execute(
                select(BotSetting).where(BotSetting.key.like(f"{_KEY_PREFIX}%"))
            )).scalars().all()
            for row in rows:
                slug = row.key[len(_KEY_PREFIX):]
                emoji = _SLUG_TO_EMOJI.get(slug)
                cid = (row.value or "").strip()
                if emoji and cid:
                    mapping[emoji] = cid
        except Exception as exc:
            logger.warning("PremiumEmojiStore.get_map failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            # Keep whatever we had cached rather than wiping it on a transient error.
            return cls.cached_map()
        cls._cache = dict(mapping)
        return mapping

    @classmethod
    async def get_id(cls, session: AsyncSession, slug: str) -> str:
        row = await session.get(BotSetting, f"{_KEY_PREFIX}{slug}")
        return (row.value or "").strip() if row is not None else ""

    @classmethod
    async def set_id(cls, session: AsyncSession, slug: str, custom_id: str, *, updated_by: int | None = None) -> None:
        if not is_valid_slug(slug):
            raise KeyError(f"Unknown emoji slug: {slug}")
        key = f"{_KEY_PREFIX}{slug}"
        custom_id = (custom_id or "").strip()
        row = await session.get(BotSetting, key)
        if not custom_id:
            # Clear the mapping.
            if row is not None:
                await session.delete(row)
        elif row is None:
            session.add(BotSetting(key=key, value=custom_id, updated_by=updated_by))
        else:
            row.value = custom_id
            row.updated_by = updated_by
        await session.commit()
        # Refresh the synchronous cache so styling reflects the change at once.
        await cls.get_map(session)

    @classmethod
    async def warm(cls, session: AsyncSession) -> None:
        try:
            await cls.get_map(session)
        except Exception:
            pass
