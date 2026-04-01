from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LedgerEntryType, WalletType
from app.core.exceptions import DuplicateTransactionError, InsufficientCreditsError
from app.db.models import CreditLedger, User

logger = logging.getLogger(__name__)


@dataclass
class WalletSnapshot:
    normal_credits: int
    vip_credits: int
    total_credits: int
    has_active_vip: bool


class BillingService:
    """Atomic dual-wallet billing with ledger auditing and VIP access helpers."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _normalize_utc(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _get_wallet_balance(user: User, wallet_type: WalletType) -> int:
        return user.normal_credits if wallet_type == WalletType.NORMAL else user.vip_credits

    @staticmethod
    def _set_wallet_balance(user: User, wallet_type: WalletType, amount: int) -> None:
        if wallet_type == WalletType.NORMAL:
            user.normal_credits = amount
        else:
            user.vip_credits = amount
        user.sync_credit_balance()

    async def _create_ledger_entry(
        self,
        user_id: int,
        entry_type: LedgerEntryType,
        amount: int,
        balance_before: int,
        balance_after: int,
        reference_type: str,
        reference_id: str,
        description: str,
        wallet_type: WalletType,
    ) -> None:
        self.session.add(
            CreditLedger(
                user_id=user_id,
                type=entry_type,
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                wallet_type=wallet_type,
                reference_type=reference_type,
                reference_id=reference_id,
                description=description,
            )
        )

    async def _ensure_reference_is_unique(self, user_id: int, reference_type: str, reference_id: str) -> None:
        stmt = select(CreditLedger.id).where(
            CreditLedger.user_id == user_id,
            CreditLedger.reference_type == reference_type,
            CreditLedger.reference_id == reference_id,
        )
        if await self.session.scalar(stmt):
            raise DuplicateTransactionError(f"Transaction {reference_id} already processed.")

    async def _get_user_for_update(self, user_id: int) -> User:
        stmt = select(User).where(User.id == user_id).with_for_update()
        user = await self.session.scalar(stmt)
        if not user:
            raise ValueError("User not found.")
        return user

    async def get_wallet_snapshot(self, user_id: int) -> WalletSnapshot:
        user = await self.session.get(User, user_id)
        if not user:
            raise ValueError("User not found.")
        user.sync_credit_balance()
        return WalletSnapshot(
            normal_credits=user.normal_credits,
            vip_credits=user.vip_credits,
            total_credits=user.credit_balance,
            has_active_vip=user.has_active_vip,
        )

    async def check_balance(self, user_id: int, wallet_type: WalletType = WalletType.NORMAL) -> int:
        stmt = select(User.normal_credits, User.vip_credits).where(User.id == user_id)
        row = (await self.session.execute(stmt)).first()
        if not row:
            return 0
        normal_credits, vip_credits = row
        return normal_credits if wallet_type == WalletType.NORMAL else vip_credits

    async def deduct_credits(
        self,
        user_id: int,
        amount: int,
        reference_type: str,
        reference_id: str,
        description: str,
        wallet_type: WalletType = WalletType.NORMAL,
    ) -> int:
        if amount <= 0:
            raise ValueError("Deduction amount must be positive.")
        logger.info(
            "Billing deduct requested user_id=%s wallet=%s amount=%s reference_type=%s",
            user_id,
            wallet_type.value,
            amount,
            reference_type,
        )

        await self._ensure_reference_is_unique(user_id, reference_type, reference_id)
        user = await self._get_user_for_update(user_id)

        balance_before = self._get_wallet_balance(user, wallet_type)
        if balance_before < amount:
            logger.warning(
                "Billing deduct blocked insufficient funds user_id=%s wallet=%s required=%s available=%s",
                user_id,
                wallet_type.value,
                amount,
                balance_before,
            )
            raise InsufficientCreditsError(required=amount, available=balance_before)

        balance_after = balance_before - amount
        self._set_wallet_balance(user, wallet_type, balance_after)
        user.lifetime_credits_used += amount

        await self._create_ledger_entry(
            user_id=user.id,
            entry_type=LedgerEntryType.USAGE,
            amount=-amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            wallet_type=wallet_type,
        )

        try:
            await self.session.flush()
            await self.session.commit()
            await self.session.refresh(user)
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateTransactionError(f"Transaction {reference_id} already processed concurrently.") from exc

        logger.info(
            "Billing deduct committed user_id=%s wallet=%s amount=%s balance_after=%s reference_type=%s",
            user_id,
            wallet_type.value,
            amount,
            self._get_wallet_balance(user, wallet_type),
            reference_type,
        )

        return self._get_wallet_balance(user, wallet_type)

    async def add_credits(
        self,
        user_id: int,
        amount: int,
        entry_type: LedgerEntryType,
        reference_type: str,
        reference_id: str,
        description: str,
        wallet_type: WalletType = WalletType.NORMAL,
    ) -> int:
        if amount <= 0:
            raise ValueError("Addition amount must be positive.")
        logger.info(
            "Billing add requested user_id=%s wallet=%s amount=%s entry_type=%s reference_type=%s",
            user_id,
            wallet_type.value,
            amount,
            entry_type.value,
            reference_type,
        )

        await self._ensure_reference_is_unique(user_id, reference_type, reference_id)
        user = await self._get_user_for_update(user_id)

        balance_before = self._get_wallet_balance(user, wallet_type)
        balance_after = balance_before + amount
        self._set_wallet_balance(user, wallet_type, balance_after)

        if entry_type == LedgerEntryType.PURCHASE:
            user.lifetime_credits_purchased += amount

        await self._create_ledger_entry(
            user_id=user.id,
            entry_type=entry_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            wallet_type=wallet_type,
        )

        try:
            await self.session.flush()
            await self.session.commit()
            await self.session.refresh(user)
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateTransactionError(f"Transaction {reference_id} already processed concurrently.") from exc

        logger.info(
            "Billing add committed user_id=%s wallet=%s amount=%s balance_after=%s entry_type=%s",
            user_id,
            wallet_type.value,
            amount,
            self._get_wallet_balance(user, wallet_type),
            entry_type.value,
        )

        return self._get_wallet_balance(user, wallet_type)

    async def refund_credits(
        self,
        user_id: int,
        original_reference_id: str,
        amount: int,
        description: str,
        wallet_type: WalletType | None = None,
    ) -> int:
        stmt = select(CreditLedger).where(
            CreditLedger.user_id == user_id,
            CreditLedger.reference_id == original_reference_id,
        )
        original_ledger = await self.session.scalar(stmt)
        if not original_ledger:
            raise ValueError(f"Original transaction {original_reference_id} not found.")
        if original_ledger.amount >= 0:
            raise ValueError(f"Original transaction {original_reference_id} is not a usage transaction.")

        refund_ref_id = f"refund_{original_reference_id}"
        logger.info(
            "Billing refund requested user_id=%s wallet=%s amount=%s original_reference_id=%s",
            user_id,
            (wallet_type or original_ledger.wallet_type).value,
            amount,
            original_reference_id,
        )
        return await self.add_credits(
            user_id=user_id,
            amount=amount,
            entry_type=LedgerEntryType.REFUND,
            reference_type="refund",
            reference_id=refund_ref_id,
            description=description or f"Refund for {original_reference_id}",
            wallet_type=wallet_type or original_ledger.wallet_type,
        )

    async def grant_vip_access(
        self,
        user_id: int,
        days: int,
        reference_type: str,
        reference_id: str,
        description: str,
    ) -> datetime:
        if days <= 0:
            raise ValueError("VIP days must be positive.")
        logger.info("Billing VIP grant requested user_id=%s days=%s reference_type=%s", user_id, days, reference_type)

        await self._ensure_reference_is_unique(user_id, reference_type, reference_id)
        user = await self._get_user_for_update(user_id)

        now = datetime.now(timezone.utc)
        current_expiry = self._normalize_utc(user.vip_expire_date)
        if current_expiry is None or current_expiry <= now:
            current_expiry = now
        new_expiry = current_expiry + timedelta(days=days)

        user.is_vip = True
        user.is_premium = True
        user.vip_expire_date = new_expiry
        user.subscription_plan = "vip"
        user.subscription_expires_at = new_expiry
        user.sync_credit_balance()

        await self._create_ledger_entry(
            user_id=user.id,
            entry_type=LedgerEntryType.VIP_ACCESS,
            amount=0,
            balance_before=user.vip_credits,
            balance_after=user.vip_credits,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            wallet_type=WalletType.VIP,
        )

        try:
            await self.session.flush()
            await self.session.commit()
            await self.session.refresh(user)
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateTransactionError(f"Transaction {reference_id} already processed concurrently.") from exc

        logger.info("Billing VIP grant committed user_id=%s expires_at=%s", user_id, new_expiry.isoformat())

        return new_expiry
