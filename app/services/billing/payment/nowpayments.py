import os
import hmac
import hashlib
import json
import aiohttp
import logging
from typing import Dict, Any, Tuple
from app.services.billing.payment.base import BasePaymentProvider
from app.core.enums import TransactionStatus

logger = logging.getLogger(__name__)

class NowPaymentsProvider(BasePaymentProvider):
    provider_name = "nowpayments"
    
    def __init__(self):
        self.api_key = os.environ.get("NOWPAYMENTS_API_KEY", "")
        self.ipn_secret = os.environ.get("NOWPAYMENTS_IPN_SECRET", "")
        self.base_url = "https://api.nowpayments.io/v1"

    async def create_invoice(self, amount: float, currency: str, order_id: str, description: str, webhook_url: str) -> Dict[str, Any]:
        url = f"{self.base_url}/invoice"
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "price_amount": amount,
            "price_currency": currency,
            "order_id": order_id,
            "order_description": description,
            "ipn_callback_url": webhook_url
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "invoice_url": data.get("invoice_url"),
                        "provider_payment_id": str(data.get("id"))
                    }
                else:
                    err = await resp.text()
                    logger.error(f"NowPayments Invoice Error: {err}")
                    raise RuntimeError("Failed to create invoice with payment provider.")

    async def verify_webhook(self, payload: Dict[str, Any], headers: Dict[str, str]) -> bool:
        # NowPayments sends signature in x-nowpayments-sig header
        signature = headers.get("x-nowpayments-sig")
        if not signature:
            return False
            
        # Sort payload keys and generate HMAC
        sorted_payload = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        hmac_obj = hmac.new(self.ipn_secret.encode(), sorted_payload.encode(), hashlib.sha512)
        expected_sig = hmac_obj.hexdigest()
        
        return hmac.compare_digest(signature, expected_sig)

    def parse_webhook_status(self, payload: Dict[str, Any]) -> Tuple[str, TransactionStatus]:
        payment_id = str(payload.get("invoice_id") or payload.get("payment_id"))
        payment_status = payload.get("payment_status", "").lower()
        
        status_mapping = {
            "finished": TransactionStatus.COMPLETED,
            "failed": TransactionStatus.FAILED,
            "expired": TransactionStatus.CANCELED,
            "refunded": TransactionStatus.REFUNDED
        }
        
        # Default to PENDING if status is 'waiting', 'confirming', 'sending', etc.
        status = status_mapping.get(payment_status, TransactionStatus.PENDING)
        return payment_id, status
