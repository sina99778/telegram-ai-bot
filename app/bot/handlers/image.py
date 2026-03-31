import html

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from app.core.i18n import t
from app.db.models import User
from app.services.chat.image_orchestrator import ImageOrchestrator

image_router = Router()


@image_router.message(Command("image"), F.chat.type == "private")
async def handle_image_command(message: Message, command: CommandObject, db_user: User, image_orchestrator: ImageOrchestrator):
    if not command.args:
        return await message.reply(
            "🎨 <b>Image Generator</b>\n\nPlease provide a prompt.\n<i>Example: /image A futuristic city at sunset</i>",
            parse_mode="HTML",
        )

    prompt = command.args
    safe_prompt = html.escape(prompt)
    processing_msg = await message.reply(
        "🎨 <i>Generating your masterpiece (this may take up to 60 seconds)...</i>",
        parse_mode="HTML",
    )

    result = await image_orchestrator.process_image_request(user_id=db_user.id, prompt=prompt)
    if not result.success:
        await processing_msg.edit_text(result.error_message or "⚠️ Failed to verify generation.", parse_mode="HTML")
        return

    image_file = BufferedInputFile(result.image_bytes, filename="generated_image.png")
    try:
        await message.answer_photo(photo=image_file, caption=f"🎨 <b>Prompt:</b> {safe_prompt}", parse_mode="HTML")
    except Exception:
        await message.reply("⚠️ Failed to securely deliver the image rendering file.", parse_mode="HTML")
    finally:
        await processing_msg.delete()


@image_router.message(Command("image"), F.chat.type.in_({"group", "supergroup"}))
async def handle_group_image_command(message: Message):
    await message.reply(t("en", "group.image_private_only"), parse_mode="HTML")
