"""
app/services/exchange/providers.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pluggable USD→Toman free-market rate providers.

Each provider exposes ``async fetch_usd_toman() -> int | None`` and returns the
USD *sell* price in Toman, or ``None`` on any failure (network, parse, missing
field). Returning ``None`` is the contract for "couldn't get a rate" — the
caller then keeps the existing admin-set rate, so the bot never shows a wrong
or zero value.

Adding another source (navasan, alanchand, …) is just another class registered
in ``PROVIDERS`` below.
"""

from __future__ import annotations

import logging
import re

import aiohttp

from app.core.config import settings

logger = logging.getLogger(__name__)


def _rial_to_toman_if_needed(value: int) -> int:
    """Many Iranian feeds quote in Rial (≈10× Toman). If the number is far
    above any plausible Toman/USD rate, treat it as Rial and divide by 10."""
    return value // 10 if value > 200_000 else value

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json",
}


class BonbastProvider:
    """Reads the free-market USD rate from bonbast.com.

    bonbast has no documented public API; the page hands out a short-lived
    token that must be POSTed to ``/json``. Both the token mechanism and the
    JSON shape can change without notice, so every step is defensive and any
    problem yields ``None`` (→ keep the manual rate).
    """

    name = "bonbast"
    HOME_URL = "https://bonbast.com/"
    JSON_URL = "https://bonbast.com/json"

    # Token patterns seen in the wild — try each, stop at first match.
    _TOKEN_PATTERNS = (
        r'param\s*:\s*"([A-Za-z0-9]+)"',
        r"param\s*:\s*'([A-Za-z0-9]+)'",
        r'name="param"\s+value="([A-Za-z0-9]+)"',
        r'data-param\s*=\s*"([A-Za-z0-9]+)"',
    )

    @classmethod
    def _extract_token(cls, html: str) -> str | None:
        for pat in cls._TOKEN_PATTERNS:
            m = re.search(pat, html)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def parse_usd(data: dict) -> int | None:
        """Pull the USD sell price (Toman) out of bonbast's JSON, flexibly."""
        if not isinstance(data, dict):
            return None
        # bonbast uses usd1 (sell) / usd2 (buy); accept a few aliases.
        for key in ("usd1", "usd", "usd_sell", "usd_1"):
            if key in data and data[key] not in (None, ""):
                try:
                    return int(float(str(data[key]).replace(",", "").strip()))
                except (TypeError, ValueError):
                    continue
        return None

    async def fetch_usd_toman(self) -> int | None:
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_BROWSER_HEADERS) as session:
                async with session.get(self.HOME_URL) as resp:
                    if resp.status != 200:
                        logger.warning("bonbast home returned HTTP %s", resp.status)
                        return None
                    html = await resp.text()
                token = self._extract_token(html)
                if not token:
                    logger.warning("bonbast token not found (page layout changed?)")
                    return None
                async with session.post(
                    self.JSON_URL,
                    data={"param": token, "webdriver": "false"},
                    headers={"X-Requested-With": "XMLHttpRequest", "Referer": self.HOME_URL},
                ) as resp2:
                    if resp2.status != 200:
                        logger.warning("bonbast /json returned HTTP %s", resp2.status)
                        return None
                    data = await resp2.json(content_type=None)
            return self.parse_usd(data)
        except Exception as exc:
            logger.warning("bonbast fetch failed: %s", exc)
            return None


class TgjuProvider:
    """Reads the USD price from tgju.org's public ajax feed.

    tgju quotes the dollar in Rial (``price_dollar_rl``); we convert to Toman.
    Structure can drift, so the parser is flexible and yields None on trouble.
    Usually reachable from inside Iran (unlike bonbast).
    """

    name = "tgju"
    URL = "https://call1.tgju.org/ajax.json"

    @staticmethod
    def parse_usd(data: dict) -> int | None:
        if not isinstance(data, dict):
            return None
        current = data.get("current")
        if not isinstance(current, dict):
            return None
        node = None
        for key in ("price_dollar_rl", "price_dollar", "usd"):
            if key in current:
                node = current[key]
                break
        if node is None:  # last resort: any key mentioning "dollar"
            for k, v in current.items():
                if "dollar" in k.lower():
                    node = v
                    break
        if node is None:
            return None
        raw = node.get("p") if isinstance(node, dict) else node
        try:
            value = int(float(str(raw).replace(",", "").strip()))
        except (TypeError, ValueError):
            return None
        return _rial_to_toman_if_needed(value)

    async def fetch_usd_toman(self) -> int | None:
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_BROWSER_HEADERS) as session:
                async with session.get(self.URL) as resp:
                    if resp.status != 200:
                        logger.warning("tgju returned HTTP %s", resp.status)
                        return None
                    data = await resp.json(content_type=None)
            return self.parse_usd(data)
        except Exception as exc:
            logger.warning("tgju fetch failed: %s", exc)
            return None


class NavasanProvider:
    """navasan.tech — a paid but cheap API that quotes directly in Toman.

    Requires NAVASAN_API_KEY; without it the provider is skipped (returns None).
    """

    name = "navasan"
    URL = "http://api.navasan.tech/latest/"

    @staticmethod
    def parse_usd(data: dict) -> int | None:
        if not isinstance(data, dict):
            return None
        for key in ("usd_sell", "usd", "usd_buy"):
            node = data.get(key)
            if node is None:
                continue
            raw = node.get("value") if isinstance(node, dict) else node
            try:
                return int(float(str(raw).replace(",", "").strip()))
            except (TypeError, ValueError):
                continue
        return None

    async def fetch_usd_toman(self) -> int | None:
        key = (settings.NAVASAN_API_KEY or "").strip()
        if not key:
            return None  # no key configured → skip silently
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_BROWSER_HEADERS) as session:
                async with session.get(self.URL, params={"api_key": key, "item": "usd_sell"}) as resp:
                    if resp.status != 200:
                        logger.warning("navasan returned HTTP %s", resp.status)
                        return None
                    data = await resp.json(content_type=None)
            return self.parse_usd(data)
        except Exception as exc:
            logger.warning("navasan fetch failed: %s", exc)
            return None


# Registry — add new sources here.
PROVIDERS: dict[str, type] = {
    BonbastProvider.name: BonbastProvider,
    TgjuProvider.name: TgjuProvider,
    NavasanProvider.name: NavasanProvider,
}
