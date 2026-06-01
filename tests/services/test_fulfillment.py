import pytest

from app.core.exceptions import DuplicateTransactionError
from app.db.models import User
from app.services.billing.billing_service import BillingService
from app.services.purchase.catalog import get_product
from app.services.purchase.fulfillment import apply_product


@pytest.mark.asyncio
async def test_apply_product_grants_normal_credits(db_session, setup_base_data):
    billing = BillingService(db_session)
    user = await db_session.get(User, setup_base_data["user_id"])
    before = user.normal_credits
    product = get_product("normal_100")

    text = await apply_product(
        billing, user_id=user.id, product=product,
        payment_ref="card_1", price_label="$1.99", lang="en",
    )
    assert "100" in text
    refreshed = await db_session.get(User, user.id)
    assert refreshed.normal_credits == before + 100


@pytest.mark.asyncio
async def test_apply_product_is_idempotent(db_session, setup_base_data):
    """Re-applying the same payment_ref must NOT double-credit."""
    billing = BillingService(db_session)
    user = await db_session.get(User, setup_base_data["user_id"])
    product = get_product("vip_150")

    await apply_product(billing, user_id=user.id, product=product,
                        payment_ref="card_42", price_label="$1.99", lang="en")
    after_first = (await db_session.get(User, user.id)).vip_credits

    with pytest.raises(DuplicateTransactionError):
        await apply_product(billing, user_id=user.id, product=product,
                            payment_ref="card_42", price_label="$1.99", lang="en")

    refreshed = await db_session.get(User, user.id)
    assert refreshed.vip_credits == after_first  # unchanged by the duplicate


@pytest.mark.asyncio
async def test_apply_product_grants_vip_access(db_session, setup_base_data):
    billing = BillingService(db_session)
    user = await db_session.get(User, setup_base_data["user_id"])
    product = get_product("access_30d")

    text = await apply_product(billing, user_id=user.id, product=product,
                               payment_ref="card_7", price_label="$2.99", lang="en")
    assert "30" in text
    refreshed = await db_session.get(User, user.id)
    assert refreshed.is_vip is True
    assert refreshed.has_active_vip is True
