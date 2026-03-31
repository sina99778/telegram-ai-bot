import logging
import aiohttp
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

class NowPaymentsService:
    BASE_URL = "https://api.nowpayments.io/v1/invoice"

    @classmethod
    async def create_invoice(
        cls,
        *,
        order_id: str,
        price_usd: float,
        description: str,
        success_url: str,
        cancel_url: str,
    ) -> Optional[str]:
        """Creates a NowPayments invoice and returns the payment URL."""
        if not settings.NOWPAYMENTS_API_KEY:
            logger.error("NOWPAYMENTS_API_KEY is not set!")
            return None

        headers = {
            "x-api-key": settings.NOWPAYMENTS_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "price_amount": price_usd,
            "price_currency": "usd",
            "order_id": order_id,
            "order_description": description,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(cls.BASE_URL, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("invoice_url")
                    else:
                        logger.error(f"NowPayments API Error: {await response.text()}")
                        return None
            except Exception as e:
                logger.error(f"Failed to connect to NowPayments: {e}")
                return None
