from __future__ import annotations

import logging
import io

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import Message

from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

_TG_MAX_LENGTH: int = 4096
_SAFE_SLICE: int = 4000

chat_router = Router(name="chat")

@chat_router.message(F.photo)
async def handle_photo_message(message: Message, chat_service: ChatService) -> None:
    if message.from_user is None or not message.photo:
        return

    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
        
        photo = message.photo[-1]
        buffer = io.BytesIO()
        await message.bot.download(photo, destination=buffer)
        image_bytes = buffer.getvalue()

        text = message.caption or "Please describe this image."

        ai_reply: str = await chat_service.process_user_message(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            text=text,
            image_bytes=image_bytes,
            mime_type="image/jpeg",
        )

        if len(ai_reply) > _TG_MAX_LENGTH:
            ai_reply = ai_reply[:_SAFE_SLICE] + "\n\n… ✂️ <i>(trimmed)</i>"

        await message.answer(ai_reply, parse_mode="HTML")
        
    except Exception as e:
        logger.error("Error processing photo: %s", e, exc_info=True)
        await message.answer("⚠️ Sorry, an error occurred while processing your image. Please try again.", parse_mode=None)

@chat_router.message(F.text)
async def handle_text_message(message: Message, chat_service: ChatService) -> None:
    if message.from_user is None or message.text is None:
        return

    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
        
        ai_reply: str = await chat_service.process_user_message(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            text=message.text,
        )

        if len(ai_reply) > _TG_MAX_LENGTH:
            ai_reply = ai_reply[:_SAFE_SLICE] + "\n\n… ✂️ <i>(trimmed)</i>"

        await message.answer(ai_reply, parse_mode="HTML")
        
    except Exception as e:
        logger.error("Error processing text: %s", e, exc_info=True)
        await message.answer("⚠️ Sorry, an error occurred. Please try again.", parse_mode=None)
