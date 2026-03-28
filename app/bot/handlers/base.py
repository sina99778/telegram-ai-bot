from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.bot.keyboards.reply import get_main_menu
from app.services.chat_service import ChatService

base_router = Router(name="base")

@base_router.message(CommandStart())
async def cmd_start(message: Message, chat_service: ChatService) -> None:
    """Handle the /start command and show the main menu."""
    if message.from_user is None:
        return
        
    # Ensure user exists in DB
    await chat_service._repo.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    welcome_text = (
        f"👋 Welcome to the AI Hub, <b>{message.from_user.first_name}</b>!\n\n"
        "I am your advanced multi-modal assistant. Choose an option from the menu below to get started, "
        "or simply type a message to chat with me.\n\n"
        "💡 <i>Tip: VIP members get access to Gemini 3.1 Pro and Nano Banana 2 Image Generation!</i>"
    )

    await message.answer(
        welcome_text,
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

@base_router.message(Command("new"))
async def cmd_new(message: Message, chat_service: ChatService) -> None:
    """Reset the current conversation."""
    if message.from_user is None:
        return

    success = await chat_service.reset_conversation(message.from_user.id)
    if success:
        await message.answer("🔄 Conversation cleared! Let's start fresh.", reply_markup=get_main_menu())
    else:
        await message.answer("You don't have an active conversation to clear.")
