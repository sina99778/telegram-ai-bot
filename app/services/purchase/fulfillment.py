"""
app/services/purchase/fulfillment.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Single source of truth for turning a paid :class:`PurchaseProduct` into
wallet credits / VIP access. Used by BOTH payment paths:

  * the NowPayments IPN webhook (crypto), and
  * the card-to-card admin-approval flow.

Keeping the grant logic here guarantees the two paths stay identical and
idempotent. Each grant uses a deterministic ``reference_id`` so a retry
(duplicate IPN, double admin tap) raises :class:`DuplicateTransactionError`
inside :class:`BillingService` instead of double-crediting.
"""

from __future__ import annotations

import logging

from app.core.enums import LedgerEntryType, WalletType
from app.core.i18n import t
from app.services.billing.billing_service import BillingService
from app.services.purchase.catalog import PurchaseKind, PurchaseProduct

logger = logging.getLogger(__name__)


async def apply_product(
    billing: BillingService,
    *,
    user_id: int,
    product: PurchaseProduct,
    payment_ref: str,
    price_label: str,
    lang: str,
) -> str:
    """Grant *product* to *user_id* and return a localized success message.

    ``payment_ref`` must be unique per real payment (e.g. ``np_<payment_id>``
    or ``card_<tx_id>``); it is woven into the ledger reference_id so repeated
    fulfillment of the same payment is rejected as a duplicate.
    """
    if product.kind == PurchaseKind.NORMAL_CREDITS and product.normal_credits > 0:
        await billing.add_credits(
            user_id=user_id,
            amount=product.normal_credits,
            entry_type=LedgerEntryType.PURCHASE,
            reference_type="purchase_normal",
            reference_id=f"{payment_ref}_normal",
            description=f"Normal credits purchase {price_label}",
            wallet_type=WalletType.NORMAL,
        )
        return t(lang, "purchase.success.normal_credits", normal=product.normal_credits)

    if product.kind == PurchaseKind.VIP_CREDITS and product.vip_credits > 0:
        await billing.add_credits(
            user_id=user_id,
            amount=product.vip_credits,
            entry_type=LedgerEntryType.PURCHASE,
            reference_type="purchase_vip",
            reference_id=f"{payment_ref}_vip",
            description=f"VIP credits purchase {price_label}",
            wallet_type=WalletType.VIP,
        )
        return t(lang, "purchase.success.vip_credits", vip=product.vip_credits)

    if product.kind == PurchaseKind.VIP_ACCESS and product.vip_days > 0:
        await billing.grant_vip_access(
            user_id=user_id,
            days=product.vip_days,
            reference_type="purchase_vip_access",
            reference_id=f"{payment_ref}_access",
            description=f"VIP access purchase {price_label}",
        )
        return t(lang, "purchase.success.vip_access", days=product.vip_days)

    raise ValueError(f"Product {product.code} has nothing to grant")
