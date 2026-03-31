from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.core.enums import FeatureName
from app.core.i18n import t
from app.db.models import User
from app.services.chat.group_policy import GroupPolicyService
from app.services.chat.orchestrator import ChatOrchestrator

chat_router = Router()


async def send_chunked_message(message: Message, text: str, parse_mode: str = "HTML", chunk_size: int = 4050):
    if len(text) <= chunk_size:
        return await message.answer(text, parse_mode=parse_mode)
    for i in range(0, len(text), chunk_size):
        await message.answer(text[i:i + chunk_size], parse_mode=parse_mode)


async def _is_group_trigger(message: Message) -> bool:
    if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.is_bot:
        return True
    if not message.text:
        return False
    bot_info = await message.bot.get_me()
    return f"@{bot_info.username}".lower() in message.text.lower()


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


@chat_router.message(F.text & ~F.text.startswith("/") & (F.chat.type == "private"))
async def handle_user_message(message: Message, db_user: User, chat_orchestrator: ChatOrchestrator):
    lang = _lang(db_user)
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
        prompt=message.text,
        feature_name=feature_name,
    )

    try:
        if not result.success:
            await processing_msg.edit_text(result.text or result.error_message or t(lang, "errors.delivery_failed"), parse_mode="HTML")
            return

        if len(result.text) <= 4050:
            try:
                await processing_msg.edit_text(result.text, parse_mode="HTML")
            except Exception:
                await processing_msg.edit_text(result.text)
        else:
            await processing_msg.delete()
            await send_chunked_message(message, result.text)
    except Exception:
        await processing_msg.edit_text(t(lang, "errors.delivery_failed"))


@chat_router.message(F.text & ~F.text.startswith("/") & F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(
    message: Message,
    db_user: User,
    chat_orchestrator: ChatOrchestrator,
    group_policy_service: GroupPolicyService,
):
    if not await _is_group_trigger(message):
        return

    lang = _lang(db_user)
    prompt = message.text or ""
    decision = group_policy_service.evaluate(group_id=message.chat.id, user_id=db_user.id, prompt=prompt, lang=lang)
    if not decision.allowed:
        return await message.reply(decision.reason, parse_mode="HTML")

    processing_msg = await message.reply(t(lang, "group.thinking"), parse_mode="HTML")
    result = await chat_orchestrator.process_message(
        user_id=db_user.id,
        prompt=prompt,
        feature_name=FeatureName.FLASH_TEXT,
        allow_vip=False,
    )
    if result.success:
        group_policy_service.record_usage(group_id=message.chat.id, user_id=db_user.id)
        if len(result.text) <= 4050:
            await processing_msg.edit_text(result.text, parse_mode="HTML")
        else:
            await processing_msg.delete()
            await send_chunked_message(message, result.text)
    else:
        await processing_msg.edit_text(result.text or t(lang, "errors.delivery_failed"), parse_mode="HTML")
