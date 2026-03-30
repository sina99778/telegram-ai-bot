import uuid
import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import PaymentTransaction
from app.core.enums import TransactionStatus, LedgerEntryType
from app.services.billing.billing_service import BillingService
from app.services.billing.payment.base import BasePaymentProvider

logger = logging.getLogger(__name__)

class PaymentManager:
    def __init__(self, session: AsyncSession, billing_service: BillingService, providers: Dict[str, BasePaymentProvider]):
        self.session = session
        self.billing_service = billing_service
        self.providers = providers

    def _get_provider(self, name: str) -> BasePaymentProvider:
        provider = self.providers.get(name)
        if not provider:
            raise ValueError(f"Payment provider '{name}' is not registered.")
        return provider

    async def initialize_transaction(self, user_id: int, provider_name: str, amount: float, currency: str, credits_to_grant: int, description: str, webhook_url: str) -> str:
        """Creates a pending transaction and generates the checkout URL."""
        provider = self._get_provider(provider_name)
        idempotency_key = f"tx_init_{uuid.uuid4().hex}"
        
        # 1. Create Invoice with external provider
        invoice_data = await provider.create_invoice(
            amount=amount, 
            currency=currency, 
            order_id=idempotency_key, 
            description=description,
            webhook_url=webhook_url
        )
        
        # 2. Store PENDING transaction in our DB
        tx = PaymentTransaction(
            user_id=user_id,
            provider=provider_name,
            provider_payment_id=invoice_data["provider_payment_id"],
            amount=amount,
            currency=currency,
            credits_granted=credits_to_grant,
            status=TransactionStatus.PENDING,
            idempotency_key=idempotency_key
        )
        self.session.add(tx)
        await self.session.flush() # Flush to get tx.id and ensure constraints
        
        return invoice_data["invoice_url"]

    async def process_webhook(self, provider_name: str, payload: Dict[str, Any], headers: Dict[str, str]):
        """Handles incoming webhooks idempotently, transitions state, and grants credits if successful."""
        provider = self._get_provider(provider_name)
        
        # 1. Verify Signature
        if not await provider.verify_webhook(payload, headers):
            logger.warning(f"Invalid webhook signature for provider {provider_name}")
            raise PermissionError("Invalid webhook signature")
            
        # 2. Parse Status
        provider_payment_id, new_status = provider.parse_webhook_status(payload)
        
        # 3. Lock Transaction Row (Prevent concurrent webhook processing)
        stmt = select(PaymentTransaction).where(
            PaymentTransaction.provider == provider_name,
            PaymentTransaction.provider_payment_id == provider_payment_id
        ).with_for_update()
        
        tx = await self.session.scalar(stmt)
        if not tx:
            logger.error(f"Webhook received for unknown transaction: {provider_payment_id}")
            return # Acknowledge webhook anyway to stop provider from retrying

        # Update raw payload for audit
        tx.raw_payload = payload

        # 4. Idempotency Check: If already in a terminal state, do nothing
        if tx.status in [TransactionStatus.COMPLETED, TransactionStatus.FAILED, TransactionStatus.CANCELED, TransactionStatus.REFUNDED]:
            logger.info(f"Transaction {tx.id} already processed (Status: {tx.status}). Ignoring webhook.")
            return

        # 5. State Transition Logic
        if new_status == TransactionStatus.COMPLETED:
            # Grant credits atomically
            try:
                await self.billing_service.add_credits(
                    user_id=tx.user_id,
                    amount=tx.credits_granted,
                    entry_type=LedgerEntryType.PURCHASE,
                    reference_type="payment_tx",
                    reference_id=f"ptx_{tx.id}",
                    description=f"Purchase via {provider_name}"
                )
                tx.status = TransactionStatus.COMPLETED
                logger.info(f"Transaction {tx.id} completed. Granted {tx.credits_granted} credits to user {tx.user_id}.")
            except Exception as e:
                logger.error(f"Failed to grant credits for tx {tx.id}: {e}")
                # Don't mark as completed if granting credits failed. Let it retry or mark manual intervention.
                raise
        else:
            # Update status for FAILED/CANCELED/PENDING
            tx.status = new_status
            
        await self.session.flush()
