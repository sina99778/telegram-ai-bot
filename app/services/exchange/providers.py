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

logger = logging.getLogger(__name__)

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


# Registry — add new sources here.
PROVIDERS: dict[str, type] = {
    BonbastProvider.name: BonbastProvider,
}
