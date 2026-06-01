import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services.config.runtime_config import RuntimeConfig
from app.services.exchange.providers import BonbastProvider
from app.services.exchange.rate_updater import ExchangeRateUpdater


@pytest.fixture(autouse=True)
def _clear_runtime_cache():
    RuntimeConfig.clear_cache()
    yield
    RuntimeConfig.clear_cache()


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


class _StubProvider:
    name = "stub"

    def __init__(self, value):
        self._value = value

    async def fetch_usd_toman(self):
        return self._value


# ── Provider parsing (no network) ────────────────────────────────────────────

def test_bonbast_parse_usd_reads_sell_field():
    assert BonbastProvider.parse_usd({"usd1": "72500", "usd2": "72000"}) == 72500
    assert BonbastProvider.parse_usd({"usd": "68,300"}) == 68300
    assert BonbastProvider.parse_usd({"eur1": "80000"}) is None
    assert BonbastProvider.parse_usd("not a dict") is None


def test_bonbast_extract_token():
    html = 'something var x; data: { param: "ABC123def" }, more'
    assert BonbastProvider._extract_token(html) == "ABC123def"
    assert BonbastProvider._extract_token("no token here") is None


# ── Updater safety contract ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_updater_writes_valid_rate(session_factory):
    applied = await ExchangeRateUpdater.update_once(session_factory, provider=_StubProvider(75000))
    assert applied == 75000
    async with session_factory() as s:
        assert await RuntimeConfig.get_int(s, "usd_toman_rate") == 75000


@pytest.mark.asyncio
async def test_updater_rejects_out_of_range(session_factory):
    # Seed a known good manual rate, then feed an insane value — must not change.
    async with session_factory() as s:
        await RuntimeConfig.set_int(s, "usd_toman_rate", 70000)
    RuntimeConfig.clear_cache()

    applied = await ExchangeRateUpdater.update_once(session_factory, provider=_StubProvider(5))  # below floor
    assert applied is None
    async with session_factory() as s:
        assert await RuntimeConfig.get_int(s, "usd_toman_rate") == 70000  # unchanged


@pytest.mark.asyncio
async def test_updater_keeps_rate_when_provider_returns_none(session_factory):
    async with session_factory() as s:
        await RuntimeConfig.set_int(s, "usd_toman_rate", 71000)
    RuntimeConfig.clear_cache()

    applied = await ExchangeRateUpdater.update_once(session_factory, provider=_StubProvider(None))
    assert applied is None
    async with session_factory() as s:
        assert await RuntimeConfig.get_int(s, "usd_toman_rate") == 71000  # unchanged
