import pytest
from sqlalchemy import select
from app.services.billing.billing_service import BillingService
from app.core.exceptions import InsufficientCreditsError, DuplicateTransactionError
from app.db.models import User, CreditLedger

@pytest.mark.asyncio
async def test_deduct_credits_success(db_session, setup_base_data):
    billing = BillingService(db_session)
    user_id = setup_base_data["user_id"]
    
    new_balance = await billing.deduct_credits(
        user_id=user_id, amount=10, reference_type="chat_message", reference_id="tx_1", description="Test deduct"
    )
    await db_session.commit()
    
    assert new_balance == 90
    user = await db_session.get(User, user_id)
    assert user.credit_balance == 90
    assert user.lifetime_credits_used == 10

@pytest.mark.asyncio
async def test_deduct_credits_insufficient(db_session, setup_base_data):
    billing = BillingService(db_session)
    user_id = setup_base_data["user_id"]
    
    with pytest.raises(InsufficientCreditsError):
        await billing.deduct_credits(
            user_id=user_id, amount=200, reference_type="chat_message", reference_id="tx_2", description="Test deduct"
        )

@pytest.mark.asyncio
async def test_idempotency_duplicate_transaction(db_session, setup_base_data):
    billing = BillingService(db_session)
    user_id = setup_base_data["user_id"]
    
    # First deduction cleanly maps
    await billing.deduct_credits(user_id, 10, "chat_message", "tx_unique_1", "First call")
    await db_session.commit()
    
    # 5. Idempotency structurally maps exactly to (user_id, reference_type, reference_id) uniqueness constraint
    with pytest.raises(DuplicateTransactionError):
        await billing.deduct_credits(user_id, 10, "chat_message", "tx_unique_1", "Second identical call")

@pytest.mark.asyncio
async def test_refund_credits_expanded(db_session, setup_base_data):
    # 4. Expanded refund tests covering ledger traces and policy idempotency
    billing = BillingService(db_session)
    user_id = setup_base_data["user_id"]
    
    # 1. Deduct first to create valid original trace
    await billing.deduct_credits(user_id, 15, "image_generation", "tx_img_1", "Image Deduction")
    await db_session.commit() # Balance now 85
    
    # 2. Refund natively
    new_balance = await billing.refund_credits(user_id, "tx_img_1", 15, "Refund test")
    await db_session.commit()
    
    assert new_balance == 100
    
    # Verify accurate Ledger insertion mappings
    stmt = select(CreditLedger).where(CreditLedger.user_id == user_id).order_by(CreditLedger.id.desc())
    ledgers = (await db_session.scalars(stmt)).all()
    
    assert len(ledgers) == 2
    assert ledgers[0].amount == 15
    assert ledgers[0].type.value == "REFUND"
    assert ledgers[1].amount == -15
    assert ledgers[1].type.value == "USAGE"
    
    # Verify Refund Idempotency mapping
    with pytest.raises(DuplicateTransactionError):
         await billing.refund_credits(user_id, "tx_img_1", 15, "Double Refund attempt")
