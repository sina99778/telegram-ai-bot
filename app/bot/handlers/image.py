import html
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BufferedInputFile
from app.services.chat.image_orchestrator import ImageOrchestrator
from app.db.models import User

image_router = Router()

@image_router.message(Command("image"))
async def handle_image_command(message: Message, command: CommandObject, db_user: User, image_orchestrator: ImageOrchestrator):
    """Handles /image <prompt> commands explicitly isolated within Private Chats."""
    
    if not command.args:
        return await message.reply("🎨 <b>Image Generator</b>\n\nPlease provide a prompt.\n<i>Example: /image A futuristic city at sunset</i>", parse_mode="HTML")

    prompt = command.args
    # Escape prompt inputs rigorously before rendering them dynamically into HTML captions
    safe_prompt = html.escape(prompt)
    
    processing_msg = await message.reply("🎨 <i>Generating your masterpiece (this may take up to 60 seconds)...</i>", parse_mode="HTML")
    
    # 1. Call the Queue-Ready Image Orchestrator
    result = await image_orchestrator.process_image_request(
        user_id=db_user.id,
        prompt=prompt
    )
    
    # 2. Check explicitly using Structured ImageResult
    if not result.success:
        await processing_msg.edit_text(result.error_message or "⚠️ Failed to verify generation.", parse_mode="HTML")
        return

    # 3. Success! Send the securely returned bytes buffered
    image_file = BufferedInputFile(result.image_bytes, filename="generated_image.png")
    
    try:
        await message.answer_photo(
            photo=image_file,
            caption=f"🎨 <b>Prompt:</b> {safe_prompt}",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply("⚠️ Failed to securely deliver the image rendering file.", parse_mode="HTML")
    finally:
        # Cleanup the temporary processing message
        await processing_msg.delete()
