import logging
import aiohttp
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

class NowPaymentsService:
    BASE_URL = "https://api.nowpayments.io/v1/invoice"

    @classmethod
    async def create_invoice(cls, telegram_id: int, price_usd: float = 5.0) -> Optional[str]:
        """Creates a NowPayments invoice and returns the payment URL."""
        if not settings.NOWPAYMENTS_API_KEY:
            logger.error("NOWPAYMENTS_API_KEY is not set!")
            return None

        headers = {
            "x-api-key": settings.NOWPAYMENTS_API_KEY,
            "Content-Type": "application/json"
        }
        
        # We pass the telegram_id as the order_id so we know who paid when the webhook hits
        payload = {
            "price_amount": price_usd,
            "price_currency": "usd",
            "order_id": str(telegram_id),
            "order_description": "VIP Premium Subscription (AI Hub)",
            "success_url": "https://t.me/YourBotUsername", # Replace with actual bot link later
            "cancel_url": "https://t.me/YourBotUsername"
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
