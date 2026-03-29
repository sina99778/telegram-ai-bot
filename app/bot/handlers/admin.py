from __future__ import annotations

import logging
import asyncio

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.db.models.user import User

from app.bot.filters.admin import IsAdmin
from app.bot.keyboards.inline import get_admin_keyboard
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

@admin_router.message(Command("admin"))
async def cmd_admin_panel(message: Message) -> None:
    """Open the visual Admin Panel."""
    text = (
        "👨‍💻 <b>Admin Control Panel</b>\n\n"
        "Use the buttons below or use stealth commands:\n"
        "🟢 <code>/give &lt;telegram_id&gt; &lt;amount&gt;</code>\n"
        "👑 <code>/setvip &lt;telegram_id&gt; &lt;days&gt;</code>\n"
        "🚫 <code>/ban &lt;telegram_id&gt;</code>\n"
        "✅ <code>/unban &lt;telegram_id&gt;</code>"
    )
    await message.answer(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin_stats")
async def cq_admin_stats(callback: CallbackQuery, chat_service: ChatService) -> None:
    """Handle the stats button from the admin panel."""
    stats = await chat_service.get_bot_stats()
    text = (
        "📊 <b>Live Bot Statistics</b>\n\n"
        f"👥 Total Users: <b>{stats['users']}</b>\n"
        f"💬 Conversations: <b>{stats['conversations']}</b>\n"
        f"✉️ Messages Exchanged: <b>{stats['messages']}</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML")

@admin_router.message(Command("ban"))
async def cmd_ban(message: Message, chat_service: ChatService) -> None:
    """Ban a user. Usage: /ban 123456789"""
    db_session = chat_service._session
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
async def cmd_unban(message: Message, chat_service: ChatService) -> None:
    """Unban a user. Usage: /unban 123456789"""
    db_session = chat_service._session
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

@admin_router.message(Command("give"))
async def cmd_give_credits(message: Message, command: CommandObject, chat_service: ChatService) -> None:
    """Give premium credits to a user. Usage: /give 123456789 100"""
    db_session = chat_service._session
    try:
        args = command.args.split()
        target_id = int(args[0])
        amount = int(args[1])
        
        user = await db_session.scalar(select(User).where(User.telegram_id == target_id))
        if user:
            user.premium_credits += amount
            await db_session.commit()
            await message.answer(f"✅ Added {amount} premium credits to user <code>{target_id}</code>.\nNew Balance: {user.premium_credits}", parse_mode="HTML")
            try:
                await message.bot.send_message(chat_id=target_id, text=f"🎁 An admin just gifted you <b>{amount} Premium Credits</b>!", parse_mode="HTML")
            except Exception:
                pass
        else:
            await message.answer("⚠️ User not found in DB.")
    except Exception:
        await message.answer("⚠️ Invalid format. Use: /give <telegram_id> <amount>")

@admin_router.message(Command("setvip"))
async def cmd_set_vip(message: Message, command: CommandObject, chat_service: ChatService) -> None:
    """Manually set VIP status. Usage: /setvip 123456789 30"""
    db_session = chat_service._session
    try:
        args = command.args.split()
        target_id = int(args[0])
        days = int(args[1])
        
        user = await db_session.scalar(select(User).where(User.telegram_id == target_id))
        if user:
            user.is_vip = True
            user.vip_expire_date = datetime.now(timezone.utc) + timedelta(days=days)
            await db_session.commit()
            await message.answer(f"✅ User <code>{target_id}</code> is now VIP for {days} days.", parse_mode="HTML")
            try:
                await message.bot.send_message(chat_id=target_id, text=f"👑 Your account has been upgraded to <b>VIP</b> for {days} days by an admin!", parse_mode="HTML")
            except Exception:
                pass
        else:
            await message.answer("⚠️ User not found in DB.")
    except Exception:
        await message.answer("⚠️ Invalid format. Use: /setvip <telegram_id> <days>")

@admin_router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, chat_service: ChatService) -> None:
    """Send a message to all registered users. Usage: /broadcast Hello everyone!"""
    if not command.args:
        await message.answer("⚠️ Please provide a message. Usage: /broadcast <message>")
        return

    users = await chat_service._repo.get_all_users()
    if not users:
        await message.answer("⚠️ No users found in the database.")
        return

    await message.answer(f"⏳ Starting broadcast to {len(users)} users...")
    
    success_count = 0
    fail_count = 0
    
    for user in users:
        try:
            await message.bot.send_message(
                chat_id=user.telegram_id,
                text=f"📢 <b>Announcement</b>\n\n{command.args}",
                parse_mode="HTML"
            )
            success_count += 1
        except Exception:
            fail_count += 1
            
        # Add a small delay to avoid hitting Telegram's rate limits
        await asyncio.sleep(0.05)

    await message.answer(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"🟢 Successful: {success_count}\n"
        f"🔴 Failed (blocked bot): {fail_count}",
        parse_mode="HTML"
    )

@admin_router.message(Command("user"))
async def cmd_user_info(message: Message, command: CommandObject, chat_service: ChatService) -> None:
    """Get detailed info about a user. Usage: /user 123456789"""
    if not command.args:
        await message.answer("⚠️ Usage: /user <telegram_id>")
        return

    try:
        target_id = int(command.args)
        user = await chat_service._repo.get_user_by_telegram_id(target_id)
        
        if not user:
            await message.answer("⚠️ User not found.")
            return

        status = "👑 VIP" if user.is_vip else "🆓 Free"
        banned = "🔴 YES" if user.is_banned else "🟢 NO"
        
        text = (
            f"👤 <b>User Information</b>\n\n"
            f"<b>ID:</b> <code>{user.telegram_id}</code>\n"
            f"<b>Name:</b> {user.first_name} (@{user.username or 'N/A'})\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Banned:</b> {banned}\n\n"
            f"💰 <b>Economy:</b>\n"
            f"Normal Credits: {user.normal_credits}\n"
            f"Premium Credits: {user.premium_credits}\n\n"
            f"🔗 <b>Referral System:</b>\n"
            f"Referred By: <code>{user.referred_by or 'None'}</code>\n"
            f"Joined: {user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else 'N/A'}"
        )
        await message.answer(text, parse_mode="HTML")
        
    except ValueError:
        await message.answer("⚠️ Invalid Telegram ID. Please provide numbers only.")
