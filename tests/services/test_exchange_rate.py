import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services.config.runtime_config import RuntimeConfig
from app.services.exchange.providers import BonbastProvider, NavasanProvider, TgjuProvider
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


def test_tgju_parse_converts_rial_to_toman():
    # tgju quotes the dollar in Rial → must come back as Toman (÷10).
    assert TgjuProvider.parse_usd({"current": {"price_dollar_rl": {"p": "700,000"}}}) == 70000
    # already-Toman small numbers are kept as-is
    assert TgjuProvider.parse_usd({"current": {"usd": "72000"}}) == 72000
    # missing/garbage → None
    assert TgjuProvider.parse_usd({"current": {}}) is None
    assert TgjuProvider.parse_usd({}) is None
    assert TgjuProvider.parse_usd("nope") is None


def test_navasan_parse_reads_toman_value():
    assert NavasanProvider.parse_usd({"usd_sell": {"value": "73500"}}) == 73500
    assert NavasanProvider.parse_usd({"usd": "70,000"}) == 70000
    assert NavasanProvider.parse_usd({"eur": "80000"}) is None


def test_provider_chain_resolves_known_names():
    providers = ExchangeRateUpdater.get_providers("tgju,bonbast,navasan,bogus")
    names = [p.name for p in providers]
    assert names == ["tgju", "bonbast", "navasan"]  # bogus dropped, order preserved


@pytest.mark.asyncio
async def test_updater_falls_through_chain_to_first_working(session_factory):
    # First provider returns None (blocked), second gives a sane value → applied.
    applied = await ExchangeRateUpdater.update_once(
        session_factory,
        providers=[_StubProvider(None), _StubProvider(73000)],
    )
    assert applied == 73000
    async with session_factory() as s:
        assert await RuntimeConfig.get_int(s, "usd_toman_rate") == 73000


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
