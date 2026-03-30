import html
from aiogram import Router, F
from aiogram.types import Message
from app.services.chat.orchestrator import ChatOrchestrator
from app.db.models import User
from app.core.enums import FeatureName

chat_router = Router()

async def send_chunked_message(message: Message, text: str, parse_mode: str = "HTML", chunk_size: int = 4050):
    """Safely delivers long messages by chunking within Telegram limits (4096)."""
    if len(text) <= chunk_size:
        return await message.answer(text, parse_mode=parse_mode)
    
    # Split by chunks safely
    for i in range(0, len(text), chunk_size):
        await message.answer(text[i:i+chunk_size], parse_mode=parse_mode)

@chat_router.message(F.text & ~F.text.startswith('/') & (F.chat.type == "private"))
async def handle_user_message(message: Message, db_user: User, chat_orchestrator: ChatOrchestrator):
    """Handles strictly private standard text messages from users."""
    
    # 1. Send initial "thinking" message
    processing_msg = await message.reply("💭 <i>Thinking...</i>", parse_mode="HTML")
    
    # 3. Extract explicit conversational modes from User preferences resiliently
    # Defaulting to Flash if not explicit UI choice found
    raw_mode = db_user.preferred_text_model or getattr(db_user, 'subscription_plan', None) or 'flash'
    preferred_mode = raw_mode.lower()
        
    feature_mapping = {
        "premium": FeatureName.PRO_TEXT,
        "pro": FeatureName.PRO_TEXT,
        "flash": FeatureName.FLASH_TEXT
    }
    feature_name = feature_mapping.get(preferred_mode, FeatureName.FLASH_TEXT)
    
    # 4. Call the Atomic Orchestrator
    result = await chat_orchestrator.process_message(
        user_id=db_user.id,
        prompt=message.text,
        feature_name=feature_name
    )
    
    # 4. Safe Delivery & Chunking
    try:
        if not result.success:
            await processing_msg.edit_text(result.text or result.error_message or "Error", parse_mode="HTML")
            return

        # Replace processing message if short enough
        if len(result.text) <= 4050:
            try:
                await processing_msg.edit_text(result.text, parse_mode="HTML")
            except Exception:
                # Fallback to plain text if HTML mapping breaks intrinsically
                await processing_msg.edit_text(result.text)
        else:
            await processing_msg.delete()
            await send_chunked_message(message, result.text)
            
    except Exception as e:
        # Failsafe Error boundary
        await processing_msg.edit_text("⚠️ An error occurred delivering the response.")
