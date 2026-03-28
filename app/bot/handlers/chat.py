"""
app/bot/handlers/chat.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Catch-all handler for plain text messages.

Sends the text through the full AI pipeline
(ChatService → PromptBuilder → GeminiClient) and replies with the
model's response.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import Message

from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

# Telegram enforces a hard 4096-character limit on text messages.
_TG_MAX_LENGTH: int = 4096
# We leave a small margin for safety / appended ellipsis.
_SAFE_SLICE: int = 4000

# ── Router ────────────────────────────────────
chat_router = Router(name="chat")


@chat_router.message(F.text)
async def handle_text_message(
    message: Message,
    chat_service: ChatService,
) -> None:
    """Process any incoming text message through the AI pipeline."""

    # Guard: ignore messages without a sender or text body.
    if message.from_user is None or message.text is None:
        return

    telegram_id: int = message.from_user.id
    username: str | None = message.from_user.username
    first_name: str | None = message.from_user.first_name
    text: str = message.text

    # Show "typing…" indicator so the user knows we're working.
    try:
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        )
    except Exception:
        # Non-critical — don't let a failed chat action block the reply.
        logger.debug("Could not send typing action", exc_info=True)

    # ── Call the business-logic service ──
    ai_reply: str = await chat_service.process_user_message(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        text=text,
    )

    # ── Enforce Telegram's message-length limit ──
    if len(ai_reply) > _TG_MAX_LENGTH:
        logger.warning(
            "AI reply too long (%d chars), slicing to %d",
            len(ai_reply),
            _SAFE_SLICE,
        )
        ai_reply = ai_reply[:_SAFE_SLICE] + "\n\n… ✂️ <i>(trimmed)</i>"

    # ── Send the response ──
    try:
        await message.answer(ai_reply, parse_mode="HTML")
    except Exception:
        # If HTML parsing fails (e.g. unmatched tags from the model),
        # fall back to plain text.
        logger.warning("HTML parse failed, falling back to plain text")
        await message.answer(ai_reply, parse_mode=None)
