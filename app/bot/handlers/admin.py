from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.user import User

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

@admin_router.message(Command("ban"))
async def cmd_ban(message: Message, db_session: AsyncSession) -> None:
    """Ban a user. Usage: /ban 123456789"""
    try:
        target_id = int(message.text.split(" ")[1])
        user = await db_session.scalar(select(User).where(User.telegram_id == target_id))
        if user:
            user.is_banned = True
            await db_session.commit()
            await message.answer(f"✅ User <code>{target_id}</code> has been banned.", parse_mode="HTML")
        else:
            await message.answer("⚠️ User not found in DB.")
    except Exception:
        await message.answer("⚠️ Invalid format. Use: /ban <telegram_id>")

@admin_router.message(Command("unban"))
async def cmd_unban(message: Message, db_session: AsyncSession) -> None:
    """Unban a user. Usage: /unban 123456789"""
    try:
        target_id = int(message.text.split(" ")[1])
        user = await db_session.scalar(select(User).where(User.telegram_id == target_id))
        if user:
            user.is_banned = False
            await db_session.commit()
            await message.answer(f"✅ User <code>{target_id}</code> has been unbanned.", parse_mode="HTML")
        else:
            await message.answer("⚠️ User not found in DB.")
    except Exception:
        await message.answer("⚠️ Invalid format. Use: /unban <telegram_id>")

