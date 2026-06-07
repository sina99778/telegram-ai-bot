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

Design rule for this module: **an API call must never fail silently.** Every
path returns a JSON body with a human-readable ``reply`` (and an ``error`` code),
even on auth failure or an unexpected exception, so the Mini App can always show
the user *why* something didn't work instead of a bare "No response".
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

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

# Telegram's in-app browser caches Mini App assets aggressively; without this a
# user can keep seeing an old build after we ship a new one.
_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}

# Only these stable codes are ever sent to the client in the `error` field —
# never a raw exception string (which can leak internal/provider details).
_SAFE_ERROR_CODES = {
    "auth", "banned", "empty", "too_large", "throttled", "blocked", "server",
    "insufficient_funds", "vip_credits_depleted", "quota_exhausted", "safety_blocked",
}


def _safe_error(code: str | None) -> str | None:
    if code in _SAFE_ERROR_CODES:
        return code
    return "ai_error" if code else None


# Magic-byte signatures for the image formats the vision model accepts. We trust
# the actual bytes, not the client-supplied multipart content_type.
_IMAGE_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM")


def _looks_like_image(data: bytes) -> bool:
    if not data:
        return False
    head = data[:16]
    if head.startswith(b"RIFF") and b"WEBP" in head:
        return True
    return any(head.startswith(sig) for sig in _IMAGE_SIGNATURES)


def _auth(init_data: str | None) -> WebAppUser | None:
    """Validate initData. Returns the user or None (never raises). The reason for
    a failure is logged by :func:`validate_init_data` for server-side diagnosis."""
    return validate_init_data(
        init_data or "",
        settings.BOT_TOKEN,
        max_age_seconds=settings.WEBAPP_INITDATA_MAX_AGE_SECONDS,
    )


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
    return HTMLResponse(content=_INDEX_HTML, headers=_NO_CACHE)


@webapp_router.get("/webapp/api/me")
async def webapp_me(x_telegram_init_data: str | None = Header(default=None)) -> JSONResponse:
    wu = _auth(x_telegram_init_data)
    if not wu:
        return JSONResponse(
            {"error": "auth", "reply": t("fa", "webapp.session_expired")},
            status_code=401,
            headers=_NO_CACHE,
        )
    try:
        async with AsyncSessionLocal() as session:
            repo = ChatRepository(session)
            user = await repo.get_or_create_user(wu.telegram_id, wu.username, wu.first_name)
            if getattr(user, "is_banned", False):
                return JSONResponse(
                    {"error": "banned", "reply": t(user.language or wu.language_code or "fa", "webapp.banned")},
                    status_code=403,
                    headers=_NO_CACHE,
                )
            return JSONResponse(
                {
                    "name": user.first_name or user.username or "user",
                    "telegram_id": user.telegram_id,
                    "normal_credits": user.normal_credits,
                    "vip_credits": user.vip_credits,
                    "has_vip": user.has_active_vip,
                    "lang": user.language or wu.language_code or "fa",
                },
                headers=_NO_CACHE,
            )
    except Exception:
        logger.exception("Mini app /me failed for telegram_id=%s", wu.telegram_id)
        return JSONResponse(
            {"error": "server", "reply": t(wu.language_code or "fa", "webapp.server_error")},
            status_code=500,
            headers=_NO_CACHE,
        )


@webapp_router.post("/webapp/api/chat")
async def webapp_chat(
    x_telegram_init_data: str | None = Header(default=None),
    message: str = Form(default=""),
    file: UploadFile | None = File(default=None),
) -> JSONResponse:
    wu = _auth(x_telegram_init_data)
    if not wu:
        # 200 (not 401) so the SPA reliably renders the message in the chat bubble.
        return JSONResponse(
            {"success": False, "reply": t("fa", "webapp.session_expired"), "error": "auth"},
            headers=_NO_CACHE,
        )

    lang = wu.language_code or "fa"
    try:
        text = (message or "").strip()

        image_bytes: bytes | None = None
        file_note: str | None = None
        if file is not None:
            # Reject oversize uploads before reading the whole body into memory.
            declared_size = getattr(file, "size", None)
            if declared_size and declared_size > settings.WEBAPP_CHAT_MAX_FILE_BYTES:
                return JSONResponse(
                    {"success": False, "reply": t(lang, "webapp.too_large"), "error": "too_large"},
                    headers=_NO_CACHE,
                )
            data = await file.read()
            if len(data) > settings.WEBAPP_CHAT_MAX_FILE_BYTES:
                return JSONResponse(
                    {"success": False, "reply": t(lang, "webapp.too_large"), "error": "too_large"},
                    headers=_NO_CACHE,
                )
            # Trust the actual bytes, not the client-supplied content_type.
            if _looks_like_image(data):
                image_bytes = data
            else:
                # Non-image (or spoofed) files aren't understood by the vision
                # model yet; keep the chat flowing and tell the user.
                file_note = "unsupported_file"

        if not text and image_bytes is None:
            return JSONResponse(
                {"success": False, "reply": t(lang, "webapp.empty_message"), "error": "empty"},
                headers=_NO_CACHE,
            )

        async with AsyncSessionLocal() as session:
            repo = ChatRepository(session)
            user = await repo.get_or_create_user(wu.telegram_id, wu.username, wu.first_name)
            lang = user.language or wu.language_code or "fa"

            if getattr(user, "is_banned", False):
                return JSONResponse(
                    {"success": False, "reply": t(lang, "webapp.banned"), "error": "banned"},
                    headers=_NO_CACHE,
                )

            from app.services.security.abuse_guard import AbuseGuardService
            from app.services.security.content_filter import ContentFilterService

            throttle = await AbuseGuardService.check_private_chat(user_id=user.id, lang=lang)
            if not throttle.allowed:
                return JSONResponse(
                    {"success": False, "reply": throttle.reason, "error": "throttled"},
                    headers=_NO_CACHE,
                )

            prompt = text or t(lang, "chat.vision_default_prompt")
            content = ContentFilterService.check_text_prompt(prompt)
            if not content.allowed:
                await AbuseGuardService.record_failure(subject="private_chat", subject_id=user.id)
                return JSONResponse(
                    {"success": False, "reply": t(lang, "abuse.content_blocked"), "error": "blocked"},
                    headers=_NO_CACHE,
                )

            orchestrator = _build_orchestrator(session)
            result = await orchestrator.process_message(
                user_id=user.id,
                prompt=prompt,
                feature_name=FeatureName.FLASH_TEXT,
                image_bytes=image_bytes,
            )

            reply = result.text or t(lang, "webapp.server_error")
            if file_note == "unsupported_file" and result.success:
                reply = "📎 " + t(lang, "webapp.image_only") + "\n\n" + reply
            return JSONResponse(
                {"success": result.success, "reply": reply, "error": _safe_error(result.error_message)},
                headers=_NO_CACHE,
            )
    except Exception:
        logger.exception("Mini app chat failed for telegram_id=%s", wu.telegram_id)
        return JSONResponse(
            {"success": False, "reply": t(lang, "webapp.server_error"), "error": "server"},
            headers=_NO_CACHE,
        )
