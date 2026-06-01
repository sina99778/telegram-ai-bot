import pytest

from app.core.config import settings
from app.db.models import BotSetting, User
from app.services.config.runtime_config import RuntimeConfig
from app.services.usage.quota_service import QuotaService


@pytest.fixture(autouse=True)
def _clear_runtime_cache():
    RuntimeConfig.clear_cache()
    yield
    RuntimeConfig.clear_cache()


@pytest.mark.asyncio
async def test_get_int_falls_back_to_env_default(db_session):
    value = await RuntimeConfig.get_int(db_session, "free_daily_image")
    assert value == settings.FREE_DAILY_IMAGE_LIMIT


@pytest.mark.asyncio
async def test_set_int_overrides_and_persists(db_session):
    await RuntimeConfig.set_int(db_session, "free_daily_image", 1, updated_by=42)
    # Cache reflects the new value immediately
    assert await RuntimeConfig.get_int(db_session, "free_daily_image") == 1
    # And it was persisted to the bot_settings table
    row = await db_session.get(BotSetting, "free_daily_image")
    assert row is not None and row.value == "1" and row.updated_by == 42


@pytest.mark.asyncio
async def test_set_int_rejects_out_of_range(db_session):
    with pytest.raises(ValueError):
        await RuntimeConfig.set_int(db_session, "free_daily_image", 10_000)


@pytest.mark.asyncio
async def test_unknown_key_raises(db_session):
    with pytest.raises(KeyError):
        await RuntimeConfig.get_int(db_session, "does_not_exist")


@pytest.mark.asyncio
async def test_quota_service_honors_runtime_override(db_session, setup_base_data):
    quota = QuotaService(db_session)
    user = await db_session.get(User, setup_base_data["user_id"])

    # Default free tier
    status = await quota.get_search_status_for_user(user)
    assert status.limit == settings.SEARCH_DAILY_FREE_LIMIT

    # Admin lowers the free search limit at runtime → quota service picks it up
    await RuntimeConfig.set_int(db_session, "search_daily_free", 1)
    status = await quota.get_search_status_for_user(user)
    assert status.limit == 1


@pytest.mark.asyncio
async def test_snapshot_reports_override_flag(db_session):
    await RuntimeConfig.set_int(db_session, "inline_daily", 3)
    snapshot = {item["key"]: item for item in await RuntimeConfig.snapshot(db_session)}
    assert snapshot["inline_daily"]["value"] == 3
    assert snapshot["inline_daily"]["is_override"] is True
    # A key we didn't touch stays at its default and is not flagged as override
    assert snapshot["vip_message_cost"]["is_override"] is False
