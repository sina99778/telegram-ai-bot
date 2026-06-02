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
    def get_providers(names: str | None = None) -> list:
        """Resolve the configured comma-separated fallback chain into instances."""
        raw = names if names is not None else (settings.EXCHANGE_RATE_PROVIDER or "bonbast")
        out = []
        for token in raw.split(","):
            key = token.strip().lower()
            if not key:
                continue
            provider_cls = PROVIDERS.get(key)
            if provider_cls is None:
                logger.warning("Unknown exchange-rate provider '%s' (ignored)", key)
                continue
            out.append(provider_cls())
        return out or [PROVIDERS["bonbast"]()]

    @classmethod
    def _is_sane(cls, rate: int) -> bool:
        return settings.EXCHANGE_RATE_MIN_TOMAN <= rate <= settings.EXCHANGE_RATE_MAX_TOMAN

    @classmethod
    async def update_once(
        cls,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        providers=None,
        provider=None,
    ) -> int | None:
        """Try each provider in order; persist the first sane value. None if all fail.

        ``provider`` (singular) is accepted for convenience/tests; otherwise the
        configured ``providers`` chain is used.
        """
        if providers is None:
            providers = [provider] if provider is not None else cls.get_providers()

        for prov in providers:
            name = getattr(prov, "name", "?")
            try:
                rate = await prov.fetch_usd_toman()
            except Exception:
                logger.warning("Exchange-rate provider %s raised; trying next", name, exc_info=True)
                continue
            if rate is None:
                continue  # source unavailable/blocked → next in chain
            if not cls._is_sane(rate):
                logger.warning(
                    "Provider %s gave out-of-range rate=%s bounds=[%s,%s]; trying next",
                    name, rate, settings.EXCHANGE_RATE_MIN_TOMAN, settings.EXCHANGE_RATE_MAX_TOMAN,
                )
                continue
            async with session_factory() as session:
                await RuntimeConfig.set_int(session, "usd_toman_rate", rate)
            logger.info("USD→Toman rate auto-updated to %s via %s", rate, name)
            return rate

        logger.info("All exchange-rate providers failed; keeping the manual rate")
        return None

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
