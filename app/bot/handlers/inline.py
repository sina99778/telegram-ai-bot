from __future__ import annotations

import asyncio
import logging
import html

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent, ChosenInlineResult

from app.core.config import settings
from app.core.enums import FeatureName
from app.core.i18n import t
from app.db.models import User
from app.services.chat.orchestrator import ChatOrchestrator
from app.services.security.abuse_guard import AbuseGuardService
from app.services.security.content_filter import ContentFilterService

inline_router = Router()
logger = logging.getLogger(__name__)


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


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
            text=final_text,
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

    prompt_check = AbuseGuardService.enforce_prompt_length(
        prompt=prompt, limit=settings.PRIVATE_MAX_PROMPT_LENGTH, lang=lang
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
    )

    await query.answer(results=[article], cache_time=0, is_personal=True)


@inline_router.chosen_inline_result()
async def handle_chosen_inline_result(
    chosen_result: ChosenInlineResult, db_user: User, chat_orchestrator: ChatOrchestrator
):
    lang = _lang(db_user)
    prompt = chosen_result.query.strip()

    if not prompt:
        return

    # 1. Content fitler check
    content_check = ContentFilterService.check_text_prompt(prompt)
    if not content_check.allowed:
        await AbuseGuardService.record_failure(subject="private_chat", subject_id=db_user.id)
        msg = t(lang, "abuse.content_blocked")
        return await _safe_edit_inline(chosen_result, msg, prompt=prompt, name=chosen_result.from_user.first_name)

    # 2. Rate limit check
    throttle = await AbuseGuardService.check_private_chat(user_id=db_user.id, lang=lang)
    if not throttle.allowed:
        return await _safe_edit_inline(
            chosen_result, throttle.reason, prompt=prompt, name=chosen_result.from_user.first_name
        )

    logger.info("Inline chat accepted user_id=%s inline_message_id=%s", db_user.id, chosen_result.inline_message_id)

    raw_mode = db_user.preferred_text_model or getattr(db_user, "subscription_plan", None) or "flash"
    preferred_mode = raw_mode.lower()
    feature_mapping = {
        "premium": FeatureName.PRO_TEXT,
        "pro": FeatureName.PRO_TEXT,
        "flash": FeatureName.FLASH_TEXT,
    }
    feature_name = feature_mapping.get(preferred_mode, FeatureName.FLASH_TEXT)

    # 3. AI Generation
    try:
        result = await asyncio.wait_for(
            chat_orchestrator.process_message(
                user_id=db_user.id,
                prompt=prompt,
                feature_name=feature_name,
            ),
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Inline chat: AI timeout user_id=%s", db_user.id)
        await AbuseGuardService.record_failure(subject="private_chat", subject_id=db_user.id)
        return await _safe_edit_inline(
            chosen_result, t(lang, "errors.ai_timeout"), prompt=prompt, name=chosen_result.from_user.first_name
        )

    # 4. Delivery
    try:
        if not result.success:
            await AbuseGuardService.record_failure(subject="private_chat", subject_id=db_user.id)
            error_text = result.text or result.error_message or t(lang, "errors.delivery_failed")
            return await _safe_edit_inline(
                chosen_result, error_text, prompt=prompt, name=chosen_result.from_user.first_name
            )

        return await _safe_edit_inline(
            chosen_result, result.text, prompt=prompt, name=chosen_result.from_user.first_name
        )
    except Exception:
        await AbuseGuardService.record_failure(subject="private_chat", subject_id=db_user.id)
        return await _safe_edit_inline(
            chosen_result, t(lang, "errors.delivery_failed"), prompt=prompt, name=chosen_result.from_user.first_name
        )
