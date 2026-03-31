import pytest
from unittest.mock import AsyncMock

from app.db.models import User
from app.services.search.search_service import SearchService
from app.services.usage.quota_service import QuotaService
from app.services.chat.image_orchestrator import ImageOrchestrator
from app.services.billing.billing_service import BillingService


@pytest.mark.asyncio
async def test_search_quota_tiers(db_session, setup_base_data):
    quota = QuotaService(db_session)
    user = await db_session.get(User, setup_base_data["user_id"])

    status = await quota.get_search_status_for_user(user)
    assert status.limit == 5

    user.lifetime_credits_purchased = 10
    await db_session.commit()
    status = await quota.get_search_status_for_user(user)
    assert status.limit == 15

    user.is_vip = True
    user.vip_credits = 100
    await db_session.commit()
    status = await quota.get_search_status_for_user(user)
    assert status.limit == 25


@pytest.mark.asyncio
async def test_search_consumes_only_on_success(db_session, setup_base_data):
    quota = QuotaService(db_session)
    router = AsyncMock()
    response = AsyncMock()
    response.text = "Fresh answer"
    response.model_name = "gemini-3.1-flash-lite-preview"
    router._get_feature_config.return_value = object()
    router.route_text_request_with_config.return_value = response
    service = SearchService(db_session, router, quota)
    user = await db_session.get(User, setup_base_data["user_id"])

    result = await service.search_for_user(user=user, query="latest ai news today")
    assert result.success is True
    status = await quota.get_search_status_for_user(user)
    assert status.used == 1

    router.route_text_request_with_config.side_effect = RuntimeError("boom")
    await service.search_for_user(user=user, query="fail this search")
    status = await quota.get_search_status_for_user(user)
    assert status.used == 1


@pytest.mark.asyncio
async def test_free_image_quota_without_vip_billing(db_session, setup_base_data):
    router = AsyncMock()
    router.route_image_request.return_value = b"image-bytes"
    billing = BillingService(db_session)
    quota = QuotaService(db_session)
    orchestrator = ImageOrchestrator(db_session, billing, router, quota)
    user = await db_session.get(User, setup_base_data["user_id"])

    user.normal_credits = 100
    user.vip_credits = 0
    user.is_premium = False
    user.is_vip = False
    await db_session.commit()

    for _ in range(5):
        result = await orchestrator.process_image_request(user.id, "sunset")
        assert result.success is True

    refreshed = await db_session.get(type(user), user.id)
    assert refreshed.vip_credits == 0

    blocked = await orchestrator.process_image_request(user.id, "one more")
    assert blocked.success is False
    assert blocked.error_code == "free_quota_exhausted"


@pytest.mark.asyncio
async def test_premium_image_uses_vip_credits_without_daily_cap(db_session, setup_base_data):
    router = AsyncMock()
    router.route_image_request.return_value = b"image-bytes"
    billing = BillingService(db_session)
    quota = QuotaService(db_session)
    orchestrator = ImageOrchestrator(db_session, billing, router, quota)
    user = await db_session.get(User, setup_base_data["user_id"])

    user.is_premium = True
    user.vip_credits = 50
    await db_session.commit()

    result = await orchestrator.process_image_request(user.id, "premium sunset")
    assert result.success is True
    refreshed = await db_session.get(type(user), user.id)
    assert refreshed.vip_credits == 40
