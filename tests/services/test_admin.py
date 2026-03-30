import pytest
from app.services.admin.admin_service import AdminService
from app.services.billing.billing_service import BillingService
from app.db.models import FeatureConfig, User
from app.core.enums import FeatureName
from sqlalchemy import select

@pytest.mark.asyncio
async def test_admin_add_credits(db_session, setup_base_data):
    billing = BillingService(db_session)
    admin_service = AdminService(db_session, billing)
    target_tg_id = setup_base_data["telegram_id"]
    
    # Emulate robust Admin command mapping updates
    new_balance = await admin_service.add_credits_to_user(
        admin_telegram_id=99999, target_telegram_id=target_tg_id, amount=500
    )
    await db_session.commit()
    
    assert new_balance == 600

@pytest.mark.asyncio
async def test_admin_set_price(db_session, setup_base_data):
    billing = BillingService(db_session)
    admin_service = AdminService(db_session, billing)
    
    await admin_service.update_feature_price(FeatureName.FLASH_TEXT, 5)
    
    feature = await db_session.scalar(select(FeatureConfig).where(FeatureConfig.name == FeatureName.FLASH_TEXT))
    assert feature.credit_cost == 5

@pytest.mark.asyncio
async def test_get_system_stats(db_session, setup_base_data):
    billing = BillingService(db_session)
    admin_service = AdminService(db_session, billing)
    
    stats = await admin_service.get_system_stats()
    
    # 8. Verifying Payments properly map aggregate states inside reporting
    assert stats["total_users"] == 1
    assert stats["total_credits_circulation"] == 100
    assert stats["total_payments_completed"] == 1
    assert stats["total_payments_failed"] == 1
