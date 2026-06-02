"""
app/webapp/routes.py
~~~~~~~~~~~~~~~~~~~~~
FastAPI routes for the Telegram Mini App:

* ``GET  /webapp``            → serves the single-page app (HTML).
* ``GET  /webapp/api/me``     → wallet + profile snapshot for the logged-in user.
* ``POST /webapp/api/chat``   → send a chat message (optionally with an uploaded
                                image) and get the AI reply.

Every API call must carry the Telegram ``initData`` in the
``X-Telegram-Init-Data`` header; it is verified by :func:`validate_init_data`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.enums import FeatureName
from app.core.i18n import t
from app.db.session import AsyncSessionLocal
from app.db.repositories.chat_repo import ChatRepository
from app.webapp.auth import WebAppUser, validate_init_data

logger = logging.getLogger(__name__)

webapp_router = APIRouter()

_INDEX_PATH = Path(__file__).with_name("index.html")
try:
    _INDEX_HTML = _INDEX_PATH.read_text(encoding="utf-8")
except Exception:  # pragma: no cover
    _INDEX_HTML = "<!doctype html><title>Mini App</title><p>Mini app unavailable.</p>"


def _auth(init_data: str | None) -> WebAppUser:
    wu = validate_init_data(init_data or "", settings.BOT_TOKEN, max_age_seconds=settings.WEBAPP_INITDATA_MAX_AGE_SECONDS)
    if not wu:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram initData")
    return wu


def _build_orchestrator(session):
    """Construct the chat orchestrator with the same wiring as the bot middleware."""
    from app.services.ai.antigravity import AntigravityProvider
    from app.services.ai.router import ModelRouter
    from app.services.billing.billing_service import BillingService
    from app.services.chat.memory import MemoryManager
    from app.services.chat.orchestrator import ChatOrchestrator
    from app.services.queue.queue_service import QueueService

    router = ModelRouter(session, {"antigravity": AntigravityProvider()})
    return ChatOrchestrator(
        session=session,
        billing=BillingService(session),
        router=router,
        memory=MemoryManager(session),
        queue_service=QueueService(),
    )


@webapp_router.get("/webapp", response_class=HTMLResponse)
async def webapp_index() -> HTMLResponse:
    return HTMLResponse(content=_INDEX_HTML)


@webapp_router.get("/webapp/api/me")
async def webapp_me(x_telegram_init_data: str | None = Header(default=None)) -> dict:
    wu = _auth(x_telegram_init_data)
    async with AsyncSessionLocal() as session:
        repo = ChatRepository(session)
        user = await repo.get_or_create_user(wu.telegram_id, wu.username, wu.first_name)
        return {
            "name": user.first_name or user.username or "user",
            "telegram_id": user.telegram_id,
            "normal_credits": user.normal_credits,
            "vip_credits": user.vip_credits,
            "has_vip": user.has_active_vip,
            "lang": user.language or wu.language_code or "fa",
        }


@webapp_router.post("/webapp/api/chat")
async def webapp_chat(
    x_telegram_init_data: str | None = Header(default=None),
    message: str = Form(default=""),
    file: UploadFile | None = File(default=None),
) -> dict:
    wu = _auth(x_telegram_init_data)
    text = (message or "").strip()

    image_bytes: bytes | None = None
    file_note: str | None = None
    if file is not None:
        data = await file.read()
        if len(data) > settings.WEBAPP_CHAT_MAX_FILE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
        if (file.content_type or "").startswith("image/"):
            image_bytes = data
        else:
            # Non-image files aren't understood by the vision model yet; keep
            # the chat flowing and tell the user.
            file_note = "unsupported_file"

    if not text and image_bytes is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty message")

    async with AsyncSessionLocal() as session:
        repo = ChatRepository(session)
        user = await repo.get_or_create_user(wu.telegram_id, wu.username, wu.first_name)
        lang = user.language or wu.language_code or "fa"

        from app.services.security.abuse_guard import AbuseGuardService
        from app.services.security.content_filter import ContentFilterService

        throttle = await AbuseGuardService.check_private_chat(user_id=user.id, lang=lang)
        if not throttle.allowed:
            return {"success": False, "reply": throttle.reason}

        prompt = text or t(lang, "chat.vision_default_prompt")
        content = ContentFilterService.check_text_prompt(prompt)
        if not content.allowed:
            await AbuseGuardService.record_failure(subject="private_chat", subject_id=user.id)
            return {"success": False, "reply": t(lang, "abuse.content_blocked")}

        orchestrator = _build_orchestrator(session)
        try:
            result = await orchestrator.process_message(
                user_id=user.id,
                prompt=prompt,
                feature_name=FeatureName.FLASH_TEXT,
                image_bytes=image_bytes,
            )
        except Exception:
            logger.exception("Mini app chat failed for telegram_id=%s", wu.telegram_id)
            return {"success": False, "reply": t(lang, "errors.delivery_failed")}

        reply = result.text
        if file_note == "unsupported_file" and result.success:
            reply = "📎 " + t(lang, "webapp.image_only") + "\n\n" + reply
        return {"success": result.success, "reply": reply, "error": result.error_message}
