"""
app/bot/handlers/base.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Handlers for core bot commands: ``/start``, ``/help``, and ``/new``.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

# ── Router ────────────────────────────────────
base_router = Router(name="base")


# ── /start & /help ────────────────────────────

@base_router.message(Command("start", "help"))
async def cmd_start_help(message: Message) -> None:
    """Greet the user and explain what the bot can do."""

    welcome_text = (
        "👋 <b>Welcome to the AI Assistant Bot!</b>\n"
        "\n"
        "I'm powered by Google Gemini and I can help you with "
        "questions, creative writing, coding, and more.\n"
        "\n"
        "<b>Commands:</b>\n"
        "  /start · /help — Show this message\n"
        "  /new  — Start a fresh conversation\n"
        "\n"
        "Simply type any message and I'll respond. "
        "Your conversation history is preserved until you use /new."
    )

    await message.answer(welcome_text, parse_mode="HTML")


# ── /new ──────────────────────────────────────

@base_router.message(Command("new"))
async def cmd_new_conversation(
    message: Message,
    chat_service: ChatService,
) -> None:
    """Reset the user's active conversation context."""

    if message.from_user is None:
        return

    success: bool = await chat_service.reset_conversation(
        telegram_id=message.from_user.id,
    )

    if success:
        reply = "🔄 Conversation cleared! Send me a new message to start fresh."
    else:
        reply = "ℹ️ You don't have an active conversation yet. Just type a message to begin!"

    await message.answer(reply)
    logger.info("User %d reset conversation → %s", message.from_user.id, success)
