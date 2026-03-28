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
from app.db.session import engine

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
