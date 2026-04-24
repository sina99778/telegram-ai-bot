from __future__ import annotations

import asyncio
import logging
import html

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent, ChosenInlineResult, InlineKeyboardMarkup, InlineKeyboardButton

from app.core.config import settings
from app.core.enums import FeatureName
from app.core.i18n import t
from app.db.models import User
from app.services.chat.orchestrator import ChatOrchestrator
from app.services.security.abuse_guard import AbuseGuardService
from app.services.security.content_filter import ContentFilterService
from app.services.usage.quota_service import QuotaService

inline_router = Router()
logger = logging.getLogger(__name__)


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


def _user_has_started(user: User) -> bool:
    """Users who have never pressed /start have an empty language field."""
    return bool(user.language)


async def _safe_edit_inline(
    chosen_result: ChosenInlineResult, response_text: str, prompt: str | None = None, name: str | None = None
):
    try:
        if prompt and name:
            # Reconstruct the header with the response
            final_text = f"🗣 <b>{name}:</b> {prompt}\n\n🤖 {response_text}"
        else:
            final_text = f"🤖 {response_text}"

        # Max length for inline message text is 4096
        if len(final_text) > 4096:
            if prompt and name:
                header = f"🗣 <b>{name}:</b> {prompt}\n\n🤖 "
                allowed_len = 4090 - len(header)
                final_text = header + response_text[:allowed_len] + "..."
            else:
                final_text = final_text[:4090] + "..."

        await chosen_result.bot.edit_message_text(
            inline_message_id=chosen_result.inline_message_id,
            text=final_text[:4090] + "...",
            parse_mode="HTML",
        )
    except TelegramBadRequest as tbre:
        if "can't parse entities" in str(tbre).lower():
            # Fallback to escaped text
            cleaned_response = html.escape(response_text)
            fallback_text = f"🗣 <b>{html.escape(name or '')}:</b> {html.escape(prompt or '')}\n\n🤖 {cleaned_response}"
            try:
                await chosen_result.bot.edit_message_text(
                    inline_message_id=chosen_result.inline_message_id,
                    text=fallback_text[:4090] + "...",
                    parse_mode="HTML",
                )
            except Exception as e2:
                logger.warning("Fallback edit also failed inline_id=%s: %s", chosen_result.inline_message_id, e2)
        else:
            logger.warning("Telegram error editing inline message: %s", tbre)
    except Exception as exc:
        logger.warning(
            "Failed to edit inline message inline_message_id=%s: %s",
            chosen_result.inline_message_id,
            exc,
        )
        try:
            # Bulletproof absolute fallback without any HTML
            safe_fallback = f"{name or 'User'}: {prompt}\n\nAI: {response_text}"
            await chosen_result.bot.edit_message_text(
                inline_message_id=chosen_result.inline_message_id,
                text=safe_fallback[:4000]
            )
        except Exception as absolute_exc:
            logger.error("Absolute fallback edit failed! inline_id=%s: %s", chosen_result.inline_message_id, absolute_exc)


@inline_router.inline_query()
async def handle_inline_query(query: InlineQuery, db_user: User):
    lang = _lang(db_user)
    prompt = query.query.strip()

    if not prompt:
        return await query.answer(
            results=[],
            switch_pm_text=t(lang, "inline.switch_pm"),
            switch_pm_parameter="start",
            cache_time=0,
            is_personal=True,
        )

    # ── Gate 1: User must have /start-ed the bot ──────────────
    if not _user_has_started(db_user):
        article = InlineQueryResultArticle(
            id="error_not_started",
            title=t(lang, "inline.start_required"),
            input_message_content=InputTextMessageContent(
                message_text=t(lang, "inline.start_required"), parse_mode="HTML"
            ),
        )
        return await query.answer(
            results=[article],
            switch_pm_text=t(lang, "inline.switch_pm"),
            switch_pm_parameter="start",
            cache_time=0,
            is_personal=True,
        )

    # ── Gate 2: Enforce inline prompt length (shorter than private) ──
    prompt_check = AbuseGuardService.enforce_prompt_length(
        prompt=prompt, limit=settings.INLINE_MAX_PROMPT_LENGTH, lang=lang
    )
    if not prompt_check.allowed:
        article = InlineQueryResultArticle(
            id="error_len",
            title=prompt_check.reason,
            input_message_content=InputTextMessageContent(
                message_text=prompt_check.reason, parse_mode="HTML"
            ),
        )
        return await query.answer(results=[article], cache_time=0, is_personal=True)

    article = InlineQueryResultArticle(
        id="ai_chat",
        title=t(lang, "inline.ask_ai_title"),
        description=prompt,
        input_message_content=InputTextMessageContent(
            message_text=f"🗣 <b>{query.from_user.first_name}:</b> {prompt}\n\n🤖 <i>{t(lang, 'chat.thinking')}</i>",
            parse_mode="HTML",
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏳ ...", callback_data="ignore")
        ]])
    )

    await query.answer(results=[article], cache_time=0, is_personal=True)


@inline_router.chosen_inline_result()
async def handle_chosen_inline_result(
    chosen_result: ChosenInlineResult, db_user: User, chat_orchestrator: ChatOrchestrator, quota_service: QuotaService
):
    lang = _lang(db_user)
    prompt = chosen_result.query.strip()

    if not prompt:
        return

    # ── Gate 1: Must have /start-ed ───────────────────────────
    if not _user_has_started(db_user):
        return await _safe_edit_inline(
            chosen_result,
            t(lang, "inline.start_required"),
            prompt=prompt,
            name=chosen_result.from_user.first_name,
        )

    # ── Gate 2: Daily inline quota ────────────────────────────
    inline_status = await quota_service.get_inline_status_for_user(db_user.id)
    if inline_status.exhausted:
        return await _safe_edit_inline(
            chosen_result,
            t(lang, "inline.daily_limit_reached", limit=settings.INLINE_DAILY_LIMIT),
            prompt=prompt,
            name=chosen_result.from_user.first_name,
        )

    # ── Gate 3: Content filter ────────────────────────────────
    content_check = ContentFilterService.check_text_prompt(prompt)
    if not content_check.allowed:
        await AbuseGuardService.record_failure(subject="inline_chat", subject_id=db_user.id)
        msg = t(lang, "abuse.content_blocked")
        return await _safe_edit_inline(chosen_result, msg, prompt=prompt, name=chosen_result.from_user.first_name)

    # ── Gate 4: Inline-specific burst rate limit ──────────────
    throttle = await AbuseGuardService.check_inline(user_id=db_user.id, lang=lang)
    if not throttle.allowed:
        return await _safe_edit_inline(
            chosen_result, throttle.reason, prompt=prompt, name=chosen_result.from_user.first_name
        )

    logger.info("Inline chat accepted user_id=%s inline_message_id=%s", db_user.id, chosen_result.inline_message_id)

    feature_name = FeatureName.FLASH_TEXT

    # ── AI Generation ─────────────────────────────────────────
    try:
        result = await asyncio.wait_for(
            chat_orchestrator.process_message(
                user_id=db_user.id,
                prompt=prompt,
                feature_name=feature_name,
                allow_vip=False,
                ignore_history=True,
            ),
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Inline chat: AI timeout user_id=%s", db_user.id)
        await AbuseGuardService.record_failure(subject="inline_chat", subject_id=db_user.id)
        return await _safe_edit_inline(
            chosen_result, t(lang, "errors.ai_timeout"), prompt=prompt, name=chosen_result.from_user.first_name
        )

    # ── Delivery ──────────────────────────────────────────────
    try:
        if not result.success:
            await AbuseGuardService.record_failure(subject="inline_chat", subject_id=db_user.id)
            error_text = result.text or result.error_message or t(lang, "errors.delivery_failed")
            return await _safe_edit_inline(
                chosen_result, error_text, prompt=prompt, name=chosen_result.from_user.first_name
            )

        # Track successful inline usage for daily quota
        await quota_service.consume_inline_for_user(db_user.id)

        return await _safe_edit_inline(
            chosen_result, result.text, prompt=prompt, name=chosen_result.from_user.first_name
        )
    except Exception:
        await AbuseGuardService.record_failure(subject="inline_chat", subject_id=db_user.id)
        return await _safe_edit_inline(
            chosen_result, t(lang, "errors.delivery_failed"), prompt=prompt, name=chosen_result.from_user.first_name
        )
