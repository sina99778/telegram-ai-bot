"""
app/services/exchange/rate_updater.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Background updater that refreshes the ``usd_toman_rate`` runtime setting from a
free-market provider (default: bonbast).

Safety contract
---------------
* The admin-set rate is the source of truth and the permanent fallback.
* An update is applied ONLY if the provider returns a value that passes a
  sanity range check. Any failure / out-of-range value leaves the current
  rate untouched — the bot never shows a wrong or zero rate because of the
  auto-updater.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.core.config import settings
from app.services.config.runtime_config import RuntimeConfig
from app.services.exchange.providers import PROVIDERS

logger = logging.getLogger(__name__)


class ExchangeRateUpdater:
    @staticmethod
    def get_provider(name: str | None = None):
        key = (name or settings.EXCHANGE_RATE_PROVIDER or "bonbast").lower()
        provider_cls = PROVIDERS.get(key)
        if provider_cls is None:
            logger.error("Unknown exchange-rate provider '%s'; falling back to bonbast", key)
            provider_cls = PROVIDERS["bonbast"]
        return provider_cls()

    @classmethod
    def _is_sane(cls, rate: int) -> bool:
        return settings.EXCHANGE_RATE_MIN_TOMAN <= rate <= settings.EXCHANGE_RATE_MAX_TOMAN

    @classmethod
    async def update_once(
        cls,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        provider=None,
    ) -> int | None:
        """Fetch once and persist if sane. Returns the applied rate or None."""
        provider = provider or cls.get_provider()
        rate = await provider.fetch_usd_toman()
        if rate is None:
            logger.info("Exchange-rate update skipped: provider returned no value (keeping manual rate)")
            return None
        if not cls._is_sane(rate):
            logger.warning(
                "Exchange-rate update rejected out-of-range value rate=%s bounds=[%s,%s] (keeping manual rate)",
                rate, settings.EXCHANGE_RATE_MIN_TOMAN, settings.EXCHANGE_RATE_MAX_TOMAN,
            )
            return None
        async with session_factory() as session:
            await RuntimeConfig.set_int(session, "usd_toman_rate", rate)
        logger.info("USD→Toman rate auto-updated to %s via %s", rate, provider.name)
        return rate

    @classmethod
    async def run_scheduler(cls, session_factory: async_sessionmaker[AsyncSession]) -> None:
        interval = max(settings.EXCHANGE_RATE_UPDATE_INTERVAL_SECONDS, 300)
        logger.info(
            "Exchange-rate updater started provider=%s interval=%ss",
            settings.EXCHANGE_RATE_PROVIDER, interval,
        )
        while True:
            try:
                await cls.update_once(session_factory)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Exchange-rate updater loop failed (keeping manual rate)")
            await asyncio.sleep(interval)
