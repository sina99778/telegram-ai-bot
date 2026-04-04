from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove

from app.core.config import settings
from app.core.enums import FeatureName
from app.core.i18n import t
from app.db.models import User
from app.services.chat.group_policy import GroupPolicyService
from app.services.chat.orchestrator import ChatOrchestrator
from app.services.security.abuse_guard import AbuseGuardService
from app.services.security.content_filter import ContentFilterService

chat_router = Router()
logger = logging.getLogger(__name__)


async def send_chunked_message(message: Message, text: str, parse_mode: str = "HTML", chunk_size: int = 4050):
    if len(text) <= chunk_size:
        try:
            return await message.answer(text, parse_mode=parse_mode)
        except Exception:
            return await message.answer(text)
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        try:
            await message.answer(chunk, parse_mode=parse_mode)
        except Exception:
            await message.answer(chunk)


async def _safe_edit(message: Message, text: str, *, parse_mode: str = "HTML") -> None:
    try:
        await message.edit_text(text, parse_mode=parse_mode)
    except Exception:
        await message.edit_text(text)


async def finalize_group_response(
    *,
    trigger_message: Message,
    processing_msg: Message,
    generation_coro,
    lang: str,
) -> tuple[object | None, bool]:
    try:
        logger.info("Group pipeline: AI start chat_id=%s message_id=%s", trigger_message.chat.id, trigger_message.message_id)
        result = await asyncio.wait_for(generation_coro, timeout=settings.GROUP_RESPONSE_TIMEOUT_SECONDS)
        logger.info(
            "Group pipeline: AI finished chat_id=%s message_id=%s success=%s",
            trigger_message.chat.id,
            trigger_message.message_id,
            getattr(result, "success", False),
        )
    except asyncio.TimeoutError:
        logger.warning("Group pipeline: AI timeout chat_id=%s message_id=%s", trigger_message.chat.id, trigger_message.message_id)
        await _safe_edit(processing_msg, t(lang, "group.timeout"))
        return None, False
    except Exception:
        logger.exception("Group pipeline: AI exception chat_id=%s message_id=%s", trigger_message.chat.id, trigger_message.message_id)
        await _safe_edit(processing_msg, t(lang, "errors.delivery_failed"))
        return None, False

    if not getattr(result, "success", False):
        logger.warning("Group pipeline: AI returned failure chat_id=%s message_id=%s", trigger_message.chat.id, trigger_message.message_id)
        await _safe_edit(processing_msg, getattr(result, "text", None) or t(lang, "errors.delivery_failed"))
        return result, False

    placeholder_deleted = False
    try:
        await processing_msg.delete()
        placeholder_deleted = True
        logger.info("Group pipeline: placeholder cleanup success chat_id=%s message_id=%s", trigger_message.chat.id, trigger_message.message_id)
    except Exception:
        logger.warning(
            "Group pipeline: placeholder cleanup failed chat_id=%s message_id=%s",
            trigger_message.chat.id,
            trigger_message.message_id,
            exc_info=True,
        )

    try:
        await send_chunked_message(trigger_message, result.text)
        logger.info("Group pipeline: final delivery success chat_id=%s message_id=%s", trigger_message.chat.id, trigger_message.message_id)
        return result, True
    except Exception:
        logger.exception("Group pipeline: final delivery failure chat_id=%s message_id=%s", trigger_message.chat.id, trigger_message.message_id)
        if not placeholder_deleted:
            await _safe_edit(processing_msg, t(lang, "errors.delivery_failed"))
        else:
            await trigger_message.reply(t(lang, "errors.delivery_failed"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return result, False


async def _is_group_trigger(message: Message) -> bool:
    bot_info = await message.bot.get_me()
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == bot_info.id:
            return True
    if not message.text:
        return False
    return f"@{bot_info.username}".lower() in message.text.lower()


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


@chat_router.message(F.text & ~F.text.startswith("/") & (F.chat.type == "private"))
async def handle_user_message(message: Message, db_user: User, chat_orchestrator: ChatOrchestrator):
    lang = _lang(db_user)
    prompt = message.text or ""
    prompt_check = AbuseGuardService.enforce_prompt_length(prompt=prompt, limit=settings.PRIVATE_MAX_PROMPT_LENGTH, lang=lang)
    if not prompt_check.allowed:
        return await message.reply(prompt_check.reason, parse_mode="HTML")

    content_check = ContentFilterService.check_text_prompt(prompt)
    if not content_check.allowed:
        await AbuseGuardService.record_failure(subject="private_chat", subject_id=db_user.id)
        return await message.reply(t(lang, "abuse.content_blocked"), parse_mode="HTML")

    throttle = await AbuseGuardService.check_private_chat(user_id=db_user.id, lang=lang)
    if not throttle.allowed:
        return await message.reply(throttle.reason, parse_mode="HTML")

    logger.info("Private chat accepted user_id=%s chat_id=%s", db_user.id, message.chat.id)
    processing_msg = await message.reply(t(lang, "chat.thinking"), parse_mode="HTML")

    raw_mode = db_user.preferred_text_model or getattr(db_user, "subscription_plan", None) or "flash"
    preferred_mode = raw_mode.lower()
    feature_mapping = {
        "premium": FeatureName.PRO_TEXT,
        "pro": FeatureName.PRO_TEXT,
        "flash": FeatureName.FLASH_TEXT,
    }
    feature_name = feature_mapping.get(preferred_mode, FeatureName.FLASH_TEXT)

    result = await chat_orchestrator.process_message(
        user_id=db_user.id,
        prompt=prompt,
        feature_name=feature_name,
    )

    try:
        if not result.success:
            await AbuseGuardService.record_failure(subject="private_chat", subject_id=db_user.id)
            await _safe_edit(processing_msg, result.text or result.error_message or t(lang, "errors.delivery_failed"))
            return

        if len(result.text) <= 4050:
            await _safe_edit(processing_msg, result.text)
        else:
            await processing_msg.delete()
            await send_chunked_message(message, result.text)
    except Exception:
        await AbuseGuardService.record_failure(subject="private_chat", subject_id=db_user.id)
        await _safe_edit(processing_msg, t(lang, "errors.delivery_failed"))


@chat_router.message(F.text & ~F.text.startswith("/") & F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(
    message: Message,
    db_user: User,
    chat_orchestrator: ChatOrchestrator,
    group_policy_service: GroupPolicyService,
):
    if not await _is_group_trigger(message):
        return
    logger.info("Group pipeline: trigger accepted chat_id=%s message_id=%s via=mention_or_reply", message.chat.id, message.message_id)

    if not group_policy_service.claim_message(group_id=message.chat.id, message_id=message.message_id):
        logger.info("Group pipeline: duplicate skipped chat_id=%s message_id=%s", message.chat.id, message.message_id)
        return
    logger.info("Group pipeline: dedup passed chat_id=%s message_id=%s", message.chat.id, message.message_id)

    lang = _lang(db_user)
    anomaly = await AbuseGuardService.check_group_request(group_id=message.chat.id, lang=lang)
    if not anomaly.allowed:
        logger.info("Group pipeline: blocked by anomaly containment chat_id=%s message_id=%s", message.chat.id, message.message_id)
        return await message.reply(anomaly.reason, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    prompt = message.text or ""
    decision = group_policy_service.evaluate(group_id=message.chat.id, user_id=db_user.id, prompt=prompt, lang=lang)
    if not decision.allowed:
        logger.info("Group pipeline: blocked by policy chat_id=%s message_id=%s", message.chat.id, message.message_id)
        return await message.reply(decision.reason, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

    content_check = ContentFilterService.check_text_prompt(prompt)
    if not content_check.allowed:
        await AbuseGuardService.record_failure(subject="group_request", subject_id=message.chat.id)
        logger.warning("Group pipeline: content filter blocked chat_id=%s user_id=%s category=%s", message.chat.id, db_user.id, content_check.category)
        return await message.reply(t(lang, "abuse.content_blocked"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

    logger.info("Group pipeline: cooldown/policy passed chat_id=%s message_id=%s", message.chat.id, message.message_id)

    processing_msg = await message.reply(t(lang, "group.thinking"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    logger.info("Group pipeline: placeholder sent chat_id=%s message_id=%s", message.chat.id, message.message_id)
    result, delivered = await finalize_group_response(
        trigger_message=message,
        processing_msg=processing_msg,
        generation_coro=chat_orchestrator.process_message(
            user_id=db_user.id,
            prompt=prompt,
            feature_name=FeatureName.FLASH_TEXT,
            allow_vip=False,
        ),
        lang=lang,
    )
    if delivered and result:
        group_policy_service.record_usage(group_id=message.chat.id, user_id=db_user.id)
