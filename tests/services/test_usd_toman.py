import pytest

from app.core.i18n import t
from app.services.config.runtime_config import RuntimeConfig


@pytest.fixture(autouse=True)
def _clear_runtime_cache():
    RuntimeConfig.clear_cache()
    yield
    RuntimeConfig.clear_cache()


@pytest.mark.asyncio
async def test_usd_toman_rate_defaults_to_zero(db_session):
    assert await RuntimeConfig.get_int(db_session, "usd_toman_rate") == 0


@pytest.mark.asyncio
async def test_usd_toman_rate_is_editable(db_session):
    await RuntimeConfig.set_int(db_session, "usd_toman_rate", 70000)
    assert await RuntimeConfig.get_int(db_session, "usd_toman_rate") == 70000


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_toman_line_renders_with_thousands_separator(lang):
    # $6.99 pack at 70,000 Toman/USD ≈ 489,300 Toman
    usd = 6.99
    rate = 70000
    toman = int(round(usd * rate))
    line = t(lang, "purchase.card.toman_line", toman=f"{toman:,}")
    assert "489,300" in line
    # the instructions template must accept the toman_line kwarg without error
    rendered = t(
        lang, "purchase.card.instructions",
        pack="VIP 700", price="6.99", toman_line=line,
        card_number="6037xxxx", card_holder="X", note="",
    )
    assert "489,300" in rendered


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_instructions_render_without_toman_when_rate_zero(lang):
    rendered = t(
        lang, "purchase.card.instructions",
        pack="VIP 700", price="6.99", toman_line="",
        card_number="6037xxxx", card_holder="X", note="",
    )
    assert "6.99" in rendered
    assert "Toman" not in rendered and "تومان" not in rendered
