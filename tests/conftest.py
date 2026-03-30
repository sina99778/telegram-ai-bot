import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.db.models import Base, User, FeatureConfig, PaymentTransaction
from app.core.enums import FeatureName

# --- Testing Architecture Refinement 1 & 2 ---
# Treat SQLite-based tests strictly as ultra-fast logic integration tests. 
# While SQLite enforces ACID properties, it does *not* emulate PostgreSQL's advanced 
# row-level locking (SELECT ... FOR UPDATE) natively. 
# FUTURE TEST PLAN: Create a secondary suite mapping directly to an ephemeral Docker 
# postgres instance specifically designed to hit `with_for_update()` under heavy multi-threading.

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

# 9. Factory-style Fixtures Architecture
@pytest_asyncio.fixture
def user_factory(db_session):
    async def _create_user(telegram_id: int, balance: int = 100, is_premium: bool = False):
        user = User(telegram_id=telegram_id, credit_balance=balance, is_premium=is_premium)
        db_session.add(user)
        await db_session.flush()
        return user
    return _create_user

@pytest_asyncio.fixture
def payment_factory(db_session):
    async def _create_payment(user_id: int, provider: str, amount: float, credits: int, status: str = "COMPLETED"):
        tx = PaymentTransaction(
            user_id=user_id,
            provider=provider,
            provider_payment_id=f"mock_{user_id}_{amount}",
            amount=amount,
            currency="USD",
            credits_granted=credits,
            status=status
        )
        db_session.add(tx)
        await db_session.flush()
        return tx
    return _create_payment

@pytest_asyncio.fixture(scope="function")
async def setup_base_data(db_session, user_factory, payment_factory):
    """Injects core testing scaffolding mapping Base Configs and factory yields."""
    user = await user_factory(telegram_id=123456789, balance=100)
    
    # Base Active Configs
    flash_config = FeatureConfig(name=FeatureName.FLASH_TEXT, credit_cost=1, is_active=True, provider="antigravity", model_name="gemini-3.1-flash-lite-preview")
    pro_config = FeatureConfig(name=FeatureName.PRO_TEXT, credit_cost=7, is_active=True, provider="antigravity", model_name="gemini-3.1-pro-preview")
    
    # 3. Add IMAGE_GENERATION directly to explicitly bound base testing feature configs
    img_config = FeatureConfig(name=FeatureName.IMAGE_GENERATION, credit_cost=15, is_active=True, provider="antigravity", model_name="dall-e-3")
    
    db_session.add_all([flash_config, pro_config, img_config])
    
    # 8. Add isolated Payment transactions explicitly injecting row visibility
    await payment_factory(user.id, "nowpayments", 10.0, 500, "COMPLETED")
    await payment_factory(user.id, "nowpayments", 5.0, 250, "FAILED")
    
    await db_session.commit()
    return {"user_id": user.id, "telegram_id": user.telegram_id}
