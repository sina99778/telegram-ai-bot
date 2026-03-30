import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db.models import User, CreditLedger
from app.core.enums import LedgerEntryType
from app.core.exceptions import InsufficientCreditsError, DuplicateTransactionError

logger = logging.getLogger(__name__)

class BillingService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _create_ledger_entry(
        self, user_id: int, entry_type: LedgerEntryType, amount: int, 
        balance_before: int, balance_after: int, reference_type: str, 
        reference_id: str, description: str
    ):
        """Internal method to create a ledger entry."""
        ledger = CreditLedger(
            user_id=user_id,
            type=entry_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description
        )
        self.session.add(ledger)

    async def check_balance(self, user_id: int) -> int:
        """Lock-free read for simple balance checks."""
        stmt = select(User.credit_balance).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def deduct_credits(self, user_id: int, amount: int, reference_type: str, reference_id: str, description: str) -> int:
        """Atomic deduction with row-level locking and idempotency check."""
        if amount <= 0:
            raise ValueError("Deduction amount must be positive.")

        # Composite Idempotency Check (Lock-free first for performance)
        stmt_check = select(CreditLedger.id).where(
            CreditLedger.user_id == user_id,
            CreditLedger.reference_type == reference_type,
            CreditLedger.reference_id == reference_id
        )
        if await self.session.scalar(stmt_check):
            raise DuplicateTransactionError(f"Transaction {reference_id} already processed.")

        # Row-level lock to prevent race conditions during deduction
        stmt_user = select(User).where(User.id == user_id).with_for_update()
        user = await self.session.scalar(stmt_user)

        if not user:
            raise ValueError("User not found.")

        if user.credit_balance < amount:
            raise InsufficientCreditsError(required=amount, available=user.credit_balance)

        balance_before = user.credit_balance
        user.credit_balance -= amount
        user.premium_credits = user.credit_balance
        user.lifetime_credits_used += amount

        await self._create_ledger_entry(
            user_id=user.id,
            entry_type=LedgerEntryType.USAGE,
            amount=-amount,
            balance_before=balance_before,
            balance_after=user.credit_balance,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description
        )

        try:
            await self.session.flush() # Ensure DB constraints pass without committing
            await self.session.commit() # Explicitly commit the transaction as requested
            await self.session.refresh(user)
        except IntegrityError as e:
            await self.session.rollback()
            # Catching rare race conditions on unique composite index
            raise DuplicateTransactionError(f"Transaction {reference_id} already processed concurrently.") from e

        return user.credit_balance

    async def add_credits(self, user_id: int, amount: int, entry_type: LedgerEntryType, reference_type: str, reference_id: str, description: str) -> int:
        """Atomic addition (purchases, bonuses, admin adjustments)."""
        if amount <= 0:
            raise ValueError("Addition amount must be positive.")

        stmt_check = select(CreditLedger.id).where(
            CreditLedger.user_id == user_id,
            CreditLedger.reference_type == reference_type,
            CreditLedger.reference_id == reference_id
        )
        if await self.session.scalar(stmt_check):
            raise DuplicateTransactionError(f"Transaction {reference_id} already processed.")

        stmt_user = select(User).where(User.id == user_id).with_for_update()
        user = await self.session.scalar(stmt_user)

        if not user:
            raise ValueError("User not found.")

        balance_before = user.credit_balance
        user.credit_balance += amount
        user.premium_credits = user.credit_balance
        
        if entry_type == LedgerEntryType.PURCHASE:
            user.lifetime_credits_purchased += amount

        await self._create_ledger_entry(
            user_id=user.id,
            entry_type=entry_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=user.credit_balance,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description
        )

        try:
            await self.session.flush()
            await self.session.commit() # Explicitly commit the transaction as requested
            await self.session.refresh(user)
        except IntegrityError as e:
            await self.session.rollback()
            raise DuplicateTransactionError(f"Transaction {reference_id} already processed concurrently.") from e

        return user.credit_balance

    async def refund_credits(self, user_id: int, original_reference_id: str, amount: int, description: str) -> int:
        """Atomic refund for failed AI generations or canceled operations."""
        # 1. Validate original transaction exists, belongs to user, and is a usage
        stmt_orig = select(CreditLedger).where(
            CreditLedger.user_id == user_id,
            CreditLedger.reference_id == original_reference_id
        )
        orig_ledger = await self.session.scalar(stmt_orig)
        if not orig_ledger:
            raise ValueError(f"Original transaction {original_reference_id} not found.")
        if orig_ledger.amount >= 0:
            raise ValueError(f"Original transaction {original_reference_id} is not a valid usage transaction to refund.")

        refund_ref_id = f"refund_{original_reference_id}"
        
        return await self.add_credits(
            user_id=user_id,
            amount=amount,
            entry_type=LedgerEntryType.REFUND,
            reference_type="refund",
            reference_id=refund_ref_id,
            description=description or f"Refund for {original_reference_id}"
        )
