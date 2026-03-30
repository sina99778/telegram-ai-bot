import logging
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.models import User, CreditLedger, PaymentTransaction
from app.services.billing.billing_service import BillingService
from app.core.enums import FeatureName, LedgerEntryType
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

class AdminService:
    def __init__(self, session: AsyncSession, billing: BillingService):
        self.session = session
        self.billing = billing

    async def add_credits_to_user(self, admin_telegram_id: int, target_telegram_id: int, amount: int) -> int:
        from app.core.exceptions import AppError
        import uuid
        user = await self.get_user_details(target_telegram_id)
        
        # We explicitly trigger the billing bounds mapping rather than SQL hacking
        new_balance = await self.billing.add_credits(
            user_id=user.id,
            amount=amount,
            entry_type=LedgerEntryType.ADMIN_ADJUSTMENT,
            reference_type="admin_grant",
            reference_id=f"admin_{admin_telegram_id}_grant_{uuid.uuid4().hex[:6]}",
            description=f"Admin {admin_telegram_id} explicitly granted {amount} credits."
        )
        return new_balance

    async def update_feature_price(self, feature_name: FeatureName, new_cost: int) -> bool:
        from app.db.models import FeatureConfig
        from sqlalchemy import select
        feature = await self.session.scalar(select(FeatureConfig).where(FeatureConfig.name == feature_name))
        if not feature:
            raise ValueError("Feature not natively located.")
        
        feature.credit_cost = new_cost
        return True

    async def get_system_stats(self) -> Dict[str, Any]:
        """Aggregate broad operational metrics securely reading the DB."""
        # 4. Explicit transaction mapping pattern internally without implicit dirty scopes
        async with self.session.begin():
            total_users = await self.session.scalar(select(func.count(User.id)))
            
            # 5. Expanding metrics correctly (active, consumed, paid)
            total_premium = await self.session.scalar(select(func.count(User.id)).where(User.is_premium == True))
            total_active = await self.session.scalar(select(func.count(User.id)).where(User.lifetime_credits_used > 0))
            
            total_credits_circ = await self.session.scalar(select(func.sum(User.credit_balance))) or 0
            total_lifetime_used = await self.session.scalar(select(func.sum(User.lifetime_credits_used))) or 0
            total_lifetime_purchased = await self.session.scalar(select(func.sum(User.lifetime_credits_purchased))) or 0
            
            total_payments_done = await self.session.scalar(select(func.count(PaymentTransaction.id)).where(PaymentTransaction.status == "COMPLETED"))
            total_payments_fail = await self.session.scalar(select(func.count(PaymentTransaction.id)).where(PaymentTransaction.status == "FAILED"))
            
            return {
                "total_users": total_users,
                "total_active_users": total_active,
                "total_premium": total_premium,
                "total_credits_circulation": total_credits_circ,
                "total_lifetime_used": total_lifetime_used,
                "total_lifetime_purchased": total_lifetime_purchased,
                "total_payments_completed": total_payments_done,
                "total_payments_failed": total_payments_fail
            }

    async def get_user_details(self, telegram_id: int) -> User:
        async with self.session.begin():
            user = await self.session.scalar(select(User).where(User.telegram_id == telegram_id))
            if not user:
                raise ValueError("User not explicitly found in active database schema.")
            return user

    async def get_user_ledger(self, telegram_id: int, limit: int = 10) -> List[CreditLedger]:
        user = await self.get_user_details(telegram_id)
        async with self.session.begin():
            stmt = select(CreditLedger).where(CreditLedger.user_id == user.id).order_by(CreditLedger.id.desc()).limit(limit)
            result = await self.session.scalars(stmt)
            return result.all()
