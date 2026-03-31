from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

class CheckUserStatusMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not event.from_user:
            return await handler(event, data)

        # 1. Check if user is banned in DB
        session: AsyncSession = data.get("session")
        if session:
            user = await session.scalar(select(User).where(User.telegram_id == event.from_user.id))
            if user and user.is_banned:
                return # Silently drop the update if banned

        # Skip forced join check in groups to prevent spam
        if getattr(event, "chat", None) and event.chat.type != "private":
            return await handler(event, data)

        # 2. Check Forced Channel Join
        CHANNEL_USERNAME = "@usefullbotsarchive"
        bot = data.get("bot")
        
        try:
            member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=event.from_user.id)
            if member.status in ["left", "kicked", "banned"]:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]
                ])
                await event.answer(
                    "🚨 <b>Access Denied!</b>\n\nTo use this bot and get your free daily credits, you must join our official channel first.",
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                return
        except Exception as e:
            pass # If bot is not admin in channel, let it pass temporarily

        return await handler(event, data)
