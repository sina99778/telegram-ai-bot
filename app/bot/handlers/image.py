import html

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from app.core.config import settings
from app.core.i18n import t
from app.db.models import User
from app.services.chat.image_orchestrator import ImageOrchestrator
from app.services.security.abuse_guard import AbuseGuardService

image_router = Router()


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


@image_router.message(Command("image"), F.chat.type == "private")
async def handle_image_command(message: Message, command: CommandObject, db_user: User, image_orchestrator: ImageOrchestrator):
    lang = _lang(db_user)
    if not command.args:
        return await message.reply(t(lang, "image.prompt_required"), parse_mode="HTML")

    prompt = command.args
    length_check = AbuseGuardService.enforce_prompt_length(prompt=prompt, limit=settings.IMAGE_MAX_PROMPT_LENGTH, lang=lang)
    if not length_check.allowed:
        return await message.reply(length_check.reason, parse_mode="HTML")
    throttle = await AbuseGuardService.check_image(user_id=db_user.id, lang=lang)
    if not throttle.allowed:
        return await message.reply(throttle.reason, parse_mode="HTML")

    safe_prompt = html.escape(prompt)
    processing_msg = await message.reply(t(lang, "image.generating"), parse_mode="HTML")

    try:
        result = await image_orchestrator.process_image_request(user_id=db_user.id, prompt=prompt)
    except Exception:
        await AbuseGuardService.record_failure(subject="image", subject_id=db_user.id)
        await processing_msg.edit_text(t(lang, "image.billing_temporary_issue"), parse_mode="HTML")
        return

    if not result.success:
        await AbuseGuardService.record_failure(subject="image", subject_id=db_user.id)
        topup_kb = None
        if result.error_code in {"insufficient_vip", "billing_error", "free_quota_exhausted"}:
            topup_kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=t(lang, "buttons.top_up"), callback_data="wallet:open")]]
            )
        await processing_msg.edit_text(result.error_message or t(lang, "image.failed_refunded"), parse_mode="HTML", reply_markup=topup_kb)
        return

    image_file = BufferedInputFile(result.image_bytes, filename="generated_image.png")
    try:
        await message.answer_photo(photo=image_file, caption=t(lang, "image.result_caption", prompt=safe_prompt), parse_mode="HTML")
    except Exception:
        await message.reply(t(lang, "image.delivery_failed"), parse_mode="HTML")
    finally:
        await processing_msg.delete()


@image_router.message(Command("image"), F.chat.type.in_({"group", "supergroup"}))
async def handle_group_image_command(message: Message, db_user: User):
    await message.reply(t(_lang(db_user), "group.image_private_only"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
