"""
app/main.py
~~~~~~~~~~~~
FastAPI application entry-point with Telegram webhook integration.

Run locally::

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request, status

from app.bot.dispatcher import get_dispatcher
from app.core.config import settings
from app.db.session import engine, async_session_maker
from app.db.repositories.chat_repo import ChatRepository
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Shared references (populated during lifespan) ──
bot: Bot | None = None
dp = get_dispatcher()


# ──────────────────────────────────────────────
#  Lifespan (startup / shutdown)
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage resources that live for the entire application lifecycle.

    **Startup**
      • Create the ``Bot`` instance with the configured token.
      • Register the Telegram webhook so updates are pushed to us.

    **Shutdown**
      • Remove the webhook from Telegram.
      • Close the bot's HTTP session.
      • Dispose of the SQLAlchemy async engine (release connection pool).
    """
    global bot

    # ── Startup ───────────────────────────────
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Tell Telegram to POST updates to our /webhook endpoint.
    await bot.set_webhook(
        url=settings.WEBHOOK_URL,
        secret_token=settings.WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    logger.info("Webhook registered  ·  url=%s", settings.WEBHOOK_URL)

    yield  # ← application is running

    # ── Shutdown ──────────────────────────────
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook removed")

    await bot.session.close()
    logger.info("Bot session closed")

    await engine.dispose()
    logger.info("DB engine disposed")


# ──────────────────────────────────────────────
#  FastAPI app
# ──────────────────────────────────────────────
app = FastAPI(
    title="Telegram AI Bot",
    version="0.1.0",
    lifespan=lifespan,
)


# ──────────────────────────────────────────────
#  Webhook endpoint
# ──────────────────────────────────────────────
@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    """Receive Telegram updates via webhook.

    Security
    --------
    Validates the ``X-Telegram-Bot-Api-Secret-Token`` header against
    ``settings.WEBHOOK_SECRET``.  Returns **401** on mismatch to
    prevent unauthorised payloads from being processed.
    """

    # ── Verify secret token ───────────────────
    if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        logger.warning("Webhook request with invalid secret token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid secret token",
        )

    # ── Parse & dispatch the update ───────────
    payload: dict[str, Any] = await request.json()
    update = Update.model_validate(payload, context={"bot": bot})

    # Feed the update into aiogram's dispatcher pipeline.
    await dp.feed_update(bot=bot, update=update)

    return {"status": "ok"}


# ──────────────────────────────────────────────
#  Health-check endpoint
# ──────────────────────────────────────────────
@app.get("/health")
async def health_check() -> dict[str, str]:
    """Simple liveness probe for deployment orchestrators."""
    return {"status": "ok"}

# ──────────────────────────────────────────────
#  NowPayments IPN webhook
# ──────────────────────────────────────────────
@app.post("/nowpayments-webhook")
async def nowpayments_webhook(request: Request) -> dict[str, str]:
    """Receives IPN from NowPayments when a payment is successful."""
    payload = await request.json()
    logger.info(f"Received NowPayments Webhook: {payload}")

    payment_status = payload.get("payment_status")
    order_id = payload.get("order_id") # This is our telegram_id

    if payment_status == "finished" and order_id:
        try:
            telegram_id = int(order_id)
            async with async_session_maker() as session:
                repo = ChatRepository(session)
                
                # Upgrade user for 30 days and add 500 premium credits
                expire_date = datetime.now(timezone.utc) + timedelta(days=30)
                success = await repo.upgrade_to_vip(
                    telegram_id=telegram_id, 
                    add_credits=500, 
                    expire_date=expire_date
                )
                
                if success:
                    # Notify the user via Telegram
                    try:
                        await bot.send_message(
                            chat_id=telegram_id,
                            text="🎉 <b>Payment Successful!</b>\n\nYou are now a VIP member. You received 500 Premium Credits and access to Gemini 3.1 Pro & Nano Banana 2. Enjoy!",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Could not send VIP confirmation to {telegram_id}: {e}")
                        
        except Exception as e:
            logger.error(f"Error processing NowPayments IPN: {e}")

    return {"status": "ok"}
