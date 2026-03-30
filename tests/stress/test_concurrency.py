import os
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.db.models import Base, User
from app.services.billing.billing_service import BillingService
from app.core.exceptions import InsufficientCreditsError, DuplicateTransactionError

# 1. Provide explicit PostgreSQL Engine URI mapping for rigorous locking execution
# This circumvents SQLite to strictly enforce `FOR UPDATE` ACID bound protections.
PG_TEST_DATABASE_URL = os.getenv(
    "PG_TEST_DATABASE_URL", 
    "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
)

@pytest_asyncio.fixture(scope="function")
async def pg_engine():
    # Use larger connection pool size mapped for aggressive concurrency
    engine = create_async_engine(PG_TEST_DATABASE_URL, echo=False, pool_size=20, max_overflow=20)
    
    # Truncate and rebuild strictly isolating states natively
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def pg_session_factory(pg_engine):
    """Yields a raw stateless session factory resolving perfectly to dynamically spawned DI parameters."""
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_concurrent_credit_deduction(pg_session_factory):
    """
    Scenario:
    - user starts with 10 credits
    - 10 concurrent requests try to deduct 7 credits
    - only 1 request should succeed
    - final balance must be 3
    - balance must never go negative
    """
    # Setup initial independent context
    async with pg_session_factory() as setup_session:
        user = User(telegram_id=999991, credit_balance=10)
        setup_session.add(user)
        await setup_session.commit()
        user_id = user.id

    # 2. Worker definitions explicitly mapping fully isolated AsyncSessions individually
    async def worker_deduct(worker_id: int):
        async with pg_session_factory() as session:
            billing = BillingService(session)
            try:
                await billing.deduct_credits(
                    user_id=user_id,
                    amount=7,
                    reference_type="chat_message",
                    reference_id=f"tx_concurrent_deduction_{worker_id}",
                    description=f"Concurrent Worker {worker_id} deduction attempt"
                )
                await session.commit()
                return "SUCCESS"
            except InsufficientCreditsError:
                await session.rollback()
                return "INSUFFICIENT"
            except Exception as e:
                await session.rollback()
                return f"ERROR: {e}"

    # 3. Fire concurrent transactions precisely
    tasks = [worker_deduct(i) for i in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = results.count("SUCCESS")
    insufficient_count = results.count("INSUFFICIENT")
    
    # 4. Strict assertions defining ACID integrity guarantees
    assert success_count == 1, f"Expected exactly 1 success, got {success_count}. Resolves: {results}"
    assert insufficient_count == 9, f"Expected 9 rejections via lock exhaustion, got {insufficient_count}."
    
    # 5. Re-read utilizing totally detached fresh verification scope
    async with pg_session_factory() as verify_session:
        final_user = await verify_session.get(User, user_id)
        assert final_user.credit_balance == 3, "System permitted double spending violating ACID invariants."


@pytest.mark.asyncio
async def test_concurrent_duplicate_webhook_race(pg_session_factory):
    """
    Scenario:
    - 5 concurrent webhooks attempt to grant credits utilizing strictly identical reference logic.
    - Result natively resolves 1 exact success guaranteeing idempotent bounds.
    """
    # Setup state natively
    async with pg_session_factory() as setup_session:
        user = User(telegram_id=999992, credit_balance=100)
        setup_session.add(user)
        await setup_session.commit()
        user_id = user.id

    # Common exact payload mimicking identical webhooks crossing the network simultaneously
    payment_identity_ref = "stripe_pi_123456789_exact_duplicate"

    # Worker isolated context precisely capturing independent web request
    async def worker_webhook(worker_id: int):
        async with pg_session_factory() as session:
            billing = BillingService(session)
            try:
                await billing.add_credits(
                    user_id=user_id,
                    amount=500,
                    reference_type="payment_webhook",
                    reference_id=payment_identity_ref,
                    description=f"Concurrent Webhook Delivery Process {worker_id}"
                )
                await session.commit()
                return "SUCCESS"
            except DuplicateTransactionError:
                await session.rollback()
                return "DUPLICATE"
            except Exception as e:
                await session.rollback()
                return f"ERROR: {e}"

    # Trigger explosion
    tasks = [worker_webhook(i) for i in range(5)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Validate structural invariants strictly
    success_count = results.count("SUCCESS")
    duplicate_count = results.count("DUPLICATE")
    
    assert success_count == 1, f"Expected single exact payload resolution natively, got {success_count}. Resolves: {results}"
    assert duplicate_count == 4, f"Expected EXACTLY 4 failures preventing idempotency exploits, got {duplicate_count}."

    # Final DB assertions verifying actual credit calculations purely derived mapping logic mathematically
    async with pg_session_factory() as verify_session:
        final_user = await verify_session.get(User, user_id)
        assert final_user.credit_balance == 600, "User state aggressively diverged beyond logical identical idempotency payload."
