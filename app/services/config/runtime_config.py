"""
app/services/config/runtime_config.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runtime-editable configuration backed by the ``bot_settings`` table.

Why this exists
---------------
Cost-sensitive knobs (daily quotas, per-message credit costs, output-token
caps) used to live only in environment variables, so changing them meant a
redeploy. After a surprise provider bill, operators need to clamp usage
*immediately*. ``RuntimeConfig`` lets an admin change these from Telegram via
``/setconfig`` and have the new value take effect within seconds — while still
defaulting to the env values when no override row exists.

Design
------
* Each editable knob is registered in :data:`RuntimeConfig.REGISTRY` with the
  ``Settings`` attribute it shadows plus a ``(min, max)`` validation bound.
* Reads are cached at class level for :data:`_CACHE_TTL` seconds so the hot
  message path does at most one tiny indexed PK lookup per key per TTL window,
  not one per message.
* Writes upsert the row and refresh the cache entry immediately so the change
  is visible to the writing instance at once; other app instances pick it up
  when their cache entry expires.

The cache uses ``time.monotonic()`` (process-local, immune to clock changes)
purely for TTL bookkeeping.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import BotSetting

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigSpec:
    settings_attr: str
    minimum: int
    maximum: int
    description: str


class RuntimeConfig:
    _CACHE_TTL = 30.0
    _cache: dict[str, tuple[int, float]] = {}

    # key → spec. Keys are the stable identifiers the admin types in /setconfig.
    REGISTRY: dict[str, ConfigSpec] = {
        "search_daily_free":      ConfigSpec("SEARCH_DAILY_FREE_LIMIT", 0, 1000, "Free-tier /search per day"),
        "search_daily_paid":      ConfigSpec("SEARCH_DAILY_PAID_LIMIT", 0, 1000, "Paid-tier /search per day"),
        "search_daily_vip":       ConfigSpec("SEARCH_DAILY_VIP_LIMIT", 0, 1000, "VIP-tier /search per day"),
        "search_daily_group":     ConfigSpec("SEARCH_DAILY_GROUP_LIMIT", 0, 1000, "Per-group /search per day"),
        "free_daily_image":       ConfigSpec("FREE_DAILY_IMAGE_LIMIT", 0, 1000, "Free image generations per day"),
        "free_weekly_image_edit": ConfigSpec("FREE_WEEKLY_IMAGE_EDIT_LIMIT", 0, 1000, "Free image edits per week"),
        "inline_daily":           ConfigSpec("INLINE_DAILY_LIMIT", 0, 1000, "Inline AI queries per day"),
        "normal_message_cost":    ConfigSpec("NORMAL_MESSAGE_COST", 0, 1000, "Credits per Flash message"),
        "vip_message_cost":       ConfigSpec("VIP_MESSAGE_COST", 0, 1000, "VIP credits per Pro message"),
        "max_output_tokens_flash": ConfigSpec("MAX_OUTPUT_TOKENS_FLASH", 64, 8192, "Max output tokens (Flash)"),
        "max_output_tokens_pro":   ConfigSpec("MAX_OUTPUT_TOKENS_PRO", 64, 8192, "Max output tokens (Pro)"),
    }

    # ── Helpers ──────────────────────────────────────────────────────────────

    @classmethod
    def is_valid_key(cls, key: str) -> bool:
        return key in cls.REGISTRY

    @classmethod
    def default_for(cls, key: str) -> int:
        spec = cls.REGISTRY[key]
        return int(getattr(settings, spec.settings_attr))

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    # ── Reads ────────────────────────────────────────────────────────────────

    @classmethod
    async def get_int(cls, session: AsyncSession, key: str) -> int:
        """Return the effective integer value for *key* (override → env default)."""
        if key not in cls.REGISTRY:
            raise KeyError(f"Unknown runtime-config key: {key}")

        now = time.monotonic()
        cached = cls._cache.get(key)
        if cached is not None and cached[1] > now:
            return cached[0]

        value = cls.default_for(key)
        try:
            row = await session.get(BotSetting, key)
            if row is not None:
                try:
                    value = int(row.value)
                except (TypeError, ValueError):
                    logger.warning("bot_settings has non-int value for key=%s value=%r; using default", key, row.value)
        except Exception as exc:
            # Never let a config read break the request path — fall back to env.
            logger.warning("RuntimeConfig DB read failed for key=%s (%s); using default", key, exc)

        cls._cache[key] = (value, now + cls._CACHE_TTL)
        return value

    # ── Writes ───────────────────────────────────────────────────────────────

    @classmethod
    async def set_int(cls, session: AsyncSession, key: str, value: int, *, updated_by: int | None = None) -> int:
        """Validate, persist, and cache an override. Returns the stored value."""
        if key not in cls.REGISTRY:
            raise KeyError(f"Unknown runtime-config key: {key}")
        spec = cls.REGISTRY[key]
        if not (spec.minimum <= value <= spec.maximum):
            raise ValueError(f"{key} must be between {spec.minimum} and {spec.maximum}")

        stmt = (
            pg_insert(BotSetting)
            .values(key=key, value=str(value), updated_by=updated_by)
            .on_conflict_do_update(
                index_elements=[BotSetting.key],
                set_={"value": str(value), "updated_by": updated_by},
            )
        )
        try:
            await session.execute(stmt)
            await session.commit()
        except Exception:
            # SQLite (tests) lacks ON CONFLICT for this construct in some setups;
            # fall back to a portable read-modify-write.
            await session.rollback()
            row = await session.get(BotSetting, key)
            if row is None:
                session.add(BotSetting(key=key, value=str(value), updated_by=updated_by))
            else:
                row.value = str(value)
                row.updated_by = updated_by
            await session.commit()

        cls._cache[key] = (value, time.monotonic() + cls._CACHE_TTL)
        logger.info("RuntimeConfig updated key=%s value=%s updated_by=%s", key, value, updated_by)
        return value

    # ── Introspection (for /config listing) ──────────────────────────────────

    @classmethod
    async def snapshot(cls, session: AsyncSession) -> list[dict]:
        """Return every registered key with its effective and default value."""
        out: list[dict] = []
        for key, spec in cls.REGISTRY.items():
            effective = await cls.get_int(session, key)
            default = cls.default_for(key)
            out.append(
                {
                    "key": key,
                    "value": effective,
                    "default": default,
                    "is_override": effective != default,
                    "min": spec.minimum,
                    "max": spec.maximum,
                    "description": spec.description,
                }
            )
        return out
