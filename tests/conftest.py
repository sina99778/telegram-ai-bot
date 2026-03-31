import pytest
import pytest_asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.db.models import Base, User, FeatureConfig, PaymentTransaction
from app.core.enums import FeatureName

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

@pytest_asyncio.fixture(scope="function")
async def user_factory(db_session):
    async def _create_user(telegram_id: int, balance: int = 100, is_premium: bool = False):
        user = User(
            telegram_id=telegram_id,
            credit_balance=balance,
            normal_credits=balance,
            vip_credits=0,
            is_premium=is_premium,
            language="en",
        )
        db_session.add(user)
        await db_session.flush()
        return user
    return _create_user

@pytest_asyncio.fixture(scope="function")
async def setup_base_data(db_session, user_factory):
    user = await user_factory(telegram_id=123456789, balance=100)
    flash = FeatureConfig(name=FeatureName.FLASH_TEXT, credit_cost=1, is_active=True, provider="antigravity", model_name="flash")
    pro = FeatureConfig(name=FeatureName.PRO_TEXT, credit_cost=7, is_active=True, provider="antigravity", model_name="pro")
    
    # Pre-populate a transaction to satisfy foreign keys/logic
    tx = PaymentTransaction(
        user_id=user.id, provider="test", provider_payment_id="init",
        amount=0, currency="USD", credits_granted=0, status="COMPLETED",
        idempotency_key=str(uuid.uuid4())
    )
    db_session.add_all([flash, pro, tx])
    await db_session.commit()
    return {"user_id": user.id, "telegram_id": user.telegram_id}
