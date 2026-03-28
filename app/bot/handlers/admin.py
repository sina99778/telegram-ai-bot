from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.filters.admin import IsAdmin
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

admin_router = Router(name="admin")
# Apply the IsAdmin filter to all messages in this router
admin_router.message.filter(IsAdmin())

@admin_router.message(Command("stats"))
async def cmd_stats(message: Message, chat_service: ChatService) -> None:
    """Show bot usage statistics to admins."""
    stats = await chat_service.get_bot_stats()
    
    text = (
        "📊 **Bot Statistics**\n\n"
        f"👥 Total Users: <b>{stats['users']}</b>\n"
        f"💬 Conversations: <b>{stats['conversations']}</b>\n"
        f"✉️ Messages EXchanged: <b>{stats['messages']}</b>"
    )
    
    await message.answer(text, parse_mode="HTML")
