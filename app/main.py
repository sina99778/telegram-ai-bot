"""
app/main.py
~~~~~~~~~~~~
FastAPI application entry-point with Telegram webhook integration.

Run locally::

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import hashlib
import hmac
import json
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
from app.core.enums import FeatureName
from app.db.session import engine, AsyncSessionLocal
from app.db.models import Base, FeatureConfig
from app.db.repositories.chat_repo import ChatRepository
from app.services.purchase.catalog import PurchaseKind, get_product, parse_order_id
from app.core.i18n import t
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Configure root logger so startup messages are visible in docker logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Shared references (populated during lifespan) ──
bot: Bot | None = None
dp = get_dispatcher()

# ── Startup validation ───────────────────────
_CRITICAL_SETTINGS = ("BOT_TOKEN", "WEBHOOK_URL", "WEBHOOK_SECRET", "GEMINI_API_KEY",
                       "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_HOST")


def _verify_nowpayments_signature(raw_body: bytes, signature: str | None) -> bool:
    if not settings.NOWPAYMENTS_IPN_SECRET:
        return True
    if not signature:
        return False
    signature = signature.strip()
    try:
        normalized = json.dumps(json.loads(raw_body.decode("utf-8")), separators=(",", ":"), sort_keys=True)
    except Exception:
        return False
    expected = hmac.new(
        settings.NOWPAYMENTS_IPN_SECRET.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _ensure_feature_configs() -> None:
    async with AsyncSessionLocal() as session:
        defaults = {
            FeatureName.FLASH_TEXT: {
                "credit_cost": settings.NORMAL_MESSAGE_COST,
                "description": "Standard private and group chat",
                "provider": "antigravity",
                "model_name": settings.GEMINI_MODEL_NORMAL,
                "fallback_model_name": None,
            },
            FeatureName.PRO_TEXT: {
                "credit_cost": settings.VIP_MESSAGE_COST,
                "description": "VIP private chat",
                "provider": "antigravity",
                "model_name": settings.GEMINI_MODEL_PRO,
                "fallback_model_name": settings.GEMINI_MODEL_NORMAL,
            },
            FeatureName.IMAGE_GEN: {
                "credit_cost": 10,
                "description": "Image generation",
                "provider": "antigravity",
                "model_name": settings.GEMINI_MODEL_IMAGE,
                "fallback_model_name": None,
            },
        }

        for feature_name, values in defaults.items():
            feature = await session.get(FeatureConfig, feature_name)
            if not feature:
                session.add(FeatureConfig(name=feature_name, is_active=True, **values))
                continue

            if feature_name == FeatureName.IMAGE_GEN and feature.model_name != settings.GEMINI_MODEL_IMAGE:
                feature.model_name = settings.GEMINI_MODEL_IMAGE
            if feature_name == FeatureName.FLASH_TEXT and feature.model_name != settings.GEMINI_MODEL_NORMAL:
                feature.model_name = settings.GEMINI_MODEL_NORMAL
            if feature_name == FeatureName.PRO_TEXT and feature.model_name != settings.GEMINI_MODEL_PRO:
                feature.model_name = settings.GEMINI_MODEL_PRO
            if not feature.provider:
                feature.provider = values["provider"]
            if feature.credit_cost is None:
                feature.credit_cost = values["credit_cost"]

        await session.commit()

def _validate_settings() -> list[str]:
    """Return names of required settings that are empty or placeholder."""
    missing = []
    for name in _CRITICAL_SETTINGS:
        val = getattr(settings, name, "")
        if not val or val in ("your-gemini-api-key-here", "change-me-to-a-random-string"):
            missing.append(name)
    return missing


# ──────────────────────────────────────────────
#  Lifespan (startup / shutdown)
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage resources that live for the entire application lifecycle.

    **Startup**
      • Validate critical environment variables.
      • Create the ``Bot`` instance with the configured token.
      • Register the Telegram webhook (non-fatal on failure).

    **Shutdown**
      • Remove the webhook from Telegram.
      • Close the bot's HTTP session.
      • Dispose of the SQLAlchemy async engine (release connection pool).
    """
    global bot

    # ── Validate env vars ─────────────────────
    missing = _validate_settings()
    if missing:
        logger.error("STARTUP BLOCKED — missing/placeholder env vars: %s", ", ".join(missing))
        logger.error("Copy .env.example → .env and fill in real values before starting.")
        raise SystemExit(1)

    # ── Startup ───────────────────────────────
    logger.info("Initializing bot with configured Telegram token")
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Ensure all tables exist (safe on subsequent runs — it's a no-op if they already exist)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified / created")
        await _ensure_feature_configs()
    except Exception as db_err:
        logger.critical("DATABASE CONNECTION FAILED: %s", db_err, exc_info=True)
        raise

    # Tell Telegram to POST updates to our /webhook endpoint.
    # Non-fatal: if webhook setup fails the /health endpoint still works,
    # making it easier to diagnose from outside the container.
    try:
        await bot.set_webhook(
            url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        logger.info("Webhook registered  ·  url=%s", settings.WEBHOOK_URL)
    except Exception as wh_err:
        logger.error(
            "WEBHOOK SETUP FAILED — the bot will NOT receive updates until this is fixed. "
            "URL=%s  Error: %s",
            settings.WEBHOOK_URL, wh_err,
            exc_info=True,
        )
        # Continue startup so /health is reachable for diagnostics.

    yield  # ← application is running

    # ── Shutdown ──────────────────────────────
    if bot:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook removed")
        except Exception:
            logger.warning("Could not remove webhook during shutdown", exc_info=True)

        try:
            await bot.session.close()
            logger.info("Bot session closed")
        except Exception:
            logger.warning("Could not close bot session", exc_info=True)

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
    raw_body = await request.body()
    if len(raw_body) > settings.WEBHOOK_MAX_BODY_BYTES:
        logger.warning("Webhook request rejected: body too large bytes=%s", len(raw_body))
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large")

    try:
        payload: dict[str, Any] = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("Webhook request rejected: invalid JSON")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")
    update = Update.model_validate(payload, context={"bot": bot})
    logger.info("Telegram webhook accepted update_id=%s", getattr(update, "update_id", None))

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
async def nowpayments_webhook(
    request: Request,
    x_nowpayments_sig: str | None = Header(default=None),
) -> dict[str, str]:
    """Receives IPN from NowPayments when a payment is successful."""
    raw_body = await request.body()
    if len(raw_body) > settings.NOWPAYMENTS_WEBHOOK_MAX_BODY_BYTES:
        logger.warning("NowPayments webhook rejected: body too large bytes=%s", len(raw_body))
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("NowPayments webhook rejected: invalid JSON")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")
    signature = x_nowpayments_sig or request.headers.get("x-nowpayments-sig") or request.headers.get("X-Nowpayments-Sig")
    if signature is None and settings.NOWPAYMENTS_IPN_SECRET:
        logger.warning(
            "NowPayments webhook missing signature header payment_id=%s order_id=%s",
            payload.get("payment_id"),
            payload.get("order_id"),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing signature")
    if not _verify_nowpayments_signature(raw_body, signature):
        logger.warning(
            "NowPayments webhook rejected: invalid signature payment_id=%s order_id=%s",
            payload.get("payment_id"),
            payload.get("order_id"),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payment_status = payload.get("payment_status")
    order_id = payload.get("order_id") # This is our telegram_id
    logger.info(
        "NowPayments webhook accepted status=%s order_id=%s payment_id=%s",
        payment_status,
        order_id,
        payload.get("payment_id"),
    )

    if payment_status == "finished" and order_id:
        try:
            parsed = parse_order_id(str(order_id))
            if parsed is not None:
                product_code, telegram_id = parsed
                product = get_product(product_code)
            else:
                product = None
                legacy_parts = str(order_id).split("_")
                if len(legacy_parts) >= 2 and legacy_parts[0] == "VIP":
                    telegram_id = int(legacy_parts[1])
                else:
                    telegram_id = int(order_id)

            async with AsyncSessionLocal() as session:
                repo = ChatRepository(session)
                user = await repo.get_user_by_telegram_id(telegram_id)
                
                if user:
                    from app.services.billing.billing_service import BillingService
                    from app.core.enums import LedgerEntryType, WalletType
                    
                    price_amount = float(payload.get("price_amount", 0))
                    billing = BillingService(session)
                    payment_id_str = str(payload.get("payment_id", order_id))

                    if product is not None:
                        if product.kind == PurchaseKind.NORMAL_CREDITS and product.normal_credits > 0:
                            await billing.add_credits(
                                user_id=user.id,
                                amount=product.normal_credits,
                                entry_type=LedgerEntryType.PURCHASE,
                                reference_type="nowpayments_normal_pack",
                                reference_id=f"np_{payment_id_str}",
                                description=f"Normal credits purchase ${price_amount}",
                                wallet_type=WalletType.NORMAL,
                            )
                        elif product.kind == PurchaseKind.VIP_CREDITS and product.vip_credits > 0:
                            await billing.add_credits(
                                user_id=user.id,
                                amount=product.vip_credits,
                                entry_type=LedgerEntryType.PURCHASE,
                                reference_type="nowpayments_vip_pack",
                                reference_id=f"np_{payment_id_str}",
                                description=f"VIP credits purchase ${price_amount}",
                                wallet_type=WalletType.VIP,
                            )
                        elif product.kind == PurchaseKind.VIP_ACCESS and product.vip_days > 0:
                            await billing.grant_vip_access(
                                user_id=user.id,
                                days=product.vip_days,
                                reference_type="nowpayments_vip_access",
                                reference_id=f"np_access_{payment_id_str}",
                                description=f"VIP access purchase ${price_amount}",
                            )
                    else:
                        # Backward compatibility for older order IDs:
                        await billing.add_credits(
                            user_id=user.id,
                            amount=150,
                            entry_type=LedgerEntryType.PURCHASE,
                            reference_type="nowpayments_legacy_vip_pack",
                            reference_id=f"np_{payment_id_str}",
                            description=f"Legacy VIP credits purchase ${price_amount}",
                            wallet_type=WalletType.VIP,
                        )
                        await billing.grant_vip_access(
                            user_id=user.id,
                            days=30,
                            reference_type="nowpayments_legacy_vip_access",
                            reference_id=f"np_access_{payment_id_str}",
                            description=f"Legacy VIP access purchase ${price_amount}",
                        )

                    lang = user.language if user.language else "en"
                    if product and product.kind == PurchaseKind.NORMAL_CREDITS:
                        notify_text = t(lang, "purchase.success.normal_credits", normal=product.normal_credits)
                    elif product and product.kind == PurchaseKind.VIP_CREDITS:
                        notify_text = t(lang, "purchase.success.vip_credits", vip=product.vip_credits)
                    elif product and product.kind == PurchaseKind.VIP_ACCESS:
                        notify_text = t(lang, "purchase.success.vip_access", days=product.vip_days)
                    else:
                        notify_text = "🎉 <b>Payment successful.</b>"

                    # Notify the user via Telegram
                    try:
                        await bot.send_message(
                            chat_id=telegram_id,
                            text=notify_text,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error("Could not send purchase confirmation to telegram_id=%s: %s", telegram_id, e)
                        
        except Exception as e:
            logger.error("Error processing NowPayments IPN order_id=%s: %s", order_id, e, exc_info=True)

    return {"status": "ok"}
