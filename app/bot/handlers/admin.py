from __future__ import annotations
import logging
import asyncio
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.db.models.user import User
from app.bot.filters.admin import IsAdmin
from app.bot.keyboards.inline import (
    get_admin_main_keyboard, 
    get_admin_back_keyboard,
    get_users_list_keyboard,
    get_admin_user_keyboard
)
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

admin_router = Router(name="admin")
# Secure all messages AND callbacks in this router
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# --- MAIN DASHBOARD ENTRY POINTS ---

@admin_router.message(Command("admin"))
async def cmd_admin_panel(message: Message, state: FSMContext) -> None:
    """Open the visual Admin Dashboard via command."""
    await state.clear()
    text = "👨💻 <b>Admin Control Panel</b>\n\nWelcome to the dashboard. Select an action below:"
    await message.answer(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")

@admin_router.callback_query(F.data == "adm_main_menu")
async def cq_admin_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the main dashboard from other menus."""
    await state.clear()
    text = "👨💻 <b>Admin Control Panel</b>\n\nWelcome back. Select an action below:"
    await callback.message.edit_text(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")

# --- STATISTICS ---

@admin_router.callback_query(F.data == "adm_main_stats")
async def cq_admin_stats(callback: CallbackQuery, chat_service: ChatService) -> None:
    stats = await chat_service.get_bot_stats()
    text = (
        "📊 <b>Live Bot Statistics</b>\n\n"
        f"👥 Total Users: <b>{stats.get('users', 0)}</b>\n"
        f"💬 Conversations: <b>{stats.get('conversations', 0)}</b>\n"
        f"✉️ Messages Exchanged: <b>{stats.get('messages', 0)}</b>"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")

# --- BROADCAST SYSTEM (FSM) ---

@admin_router.callback_query(F.data == "adm_main_broadcast")
async def cq_admin_broadcast_req(callback: CallbackQuery, state: FSMContext) -> None:
    text = (
        "📢 <b>Broadcast Mode</b>\n\n"
        "Please send the message you want to broadcast to ALL users now.\n"
        "<i>(Text, photos, and videos are supported. Click Back to cancel)</i>"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_broadcast)

@admin_router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast_message(message: Message, state: FSMContext, chat_service: ChatService) -> None:
    users = await chat_service._repo.get_all_users()
    if not users:
        await message.answer("⚠️ No users found in the database.", reply_markup=get_admin_back_keyboard())
        await state.clear()
        return

    status_msg = await message.answer(f"⏳ Starting broadcast to {len(users)} users...")
    success_count, fail_count = 0, 0
    
    for user in users:
        try:
            # Copy the admin's exact message (supports media/formatting)
            await message.copy_to(chat_id=user.telegram_id)
            success_count += 1
        except Exception:
            fail_count += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"🟢 Successful: {success_count}\n"
        f"🔴 Failed (blocked bot): {fail_count}",
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()

# --- PAGINATED USER MANAGEMENT ---

async def show_users_page(message_or_callback, chat_service: ChatService, page: int):
    limit, offset = 8, (page - 1) * 8
    total_users = await chat_service._repo.get_total_users_count()
    total_pages = math.ceil(total_users / limit) if total_users > 0 else 1
    users = await chat_service._repo.get_users_paginated(limit, offset)
    
    text = f"👥 <b>User Management</b>\n\nTotal Users: {total_users}\n<i>Select a user to manage:</i>"
    kb = get_users_list_keyboard(users, page, total_pages)
    
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_or_callback.answer(text, reply_markup=kb, parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("adm_page_"))
async def cq_admin_page(callback: CallbackQuery, chat_service: ChatService):
    page = int(callback.data.split("_")[2])
    await show_users_page(callback, chat_service, page)
    await callback.answer()

@admin_router.callback_query(F.data.startswith("adm_u_"))
async def cq_admin_user_detail(callback: CallbackQuery, chat_service: ChatService):
    target_id = int(callback.data.split("_")[2])
    current_page = 1 
    if callback.message.reply_markup and callback.message.reply_markup.inline_keyboard:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("adm_page_"):
                    parts = btn.callback_data.split("_")
                    if len(parts) > 2:
                        try:
                            if "Next" in btn.text: current_page = int(parts[2]) - 1
                            elif "Prev" in btn.text: current_page = int(parts[2]) + 1
                            else: current_page = int(parts[2])
                        except ValueError: pass
                        
    user = await chat_service._repo.get_user_by_telegram_id(target_id)
    if not user:
        return await callback.answer("User not found.", show_alert=True)
        
    text = (
        f"👤 <b>Managing User</b>\n\n"
        f"<b>ID:</b> <code>{user.telegram_id}</code>\n"
        f"<b>Name:</b> {user.first_name}\n"
        f"<b>VIP Status:</b> {'Yes 👑' if user.is_vip else 'No'}\n"
        f"<b>Banned:</b> {'Yes 🚫' if user.is_banned else 'No'}\n"
        f"<b>Normal Credits:</b> {user.normal_credits}\n"
        f"<b>Premium Credits:</b> {user.premium_credits}\n"
    )
    await callback.message.edit_text(
        text, 
        reply_markup=get_admin_user_keyboard(user.telegram_id, user.is_vip, user.is_banned, current_page),
        parse_mode="HTML"
    )

@admin_router.callback_query(F.data.startswith("adm_"))
async def cq_admin_actions(callback: CallbackQuery, chat_service: ChatService):
    if callback.data.startswith("adm_main_") or callback.data.startswith("adm_page_") or callback.data.startswith("adm_u_"):
        return
        
    parts = callback.data.split("_")
    if len(parts) < 4: return
    action, target_id, current_page = parts[1], int(parts[2]), int(parts[3])
    
    user = await chat_service._repo.get_user_by_telegram_id(target_id)
    if not user:
        return await callback.answer("User not found.", show_alert=True)
        
    if action == "cred":
        user.premium_credits += 50
        msg = f"✅ Added 50 Premium Credits. Total: {user.premium_credits}"
    elif action == "vip":
        user.is_vip = not user.is_vip
        msg = f"✅ VIP Status changed to: {user.is_vip}"
    elif action == "ban":
        user.is_banned = not user.is_banned
        msg = f"✅ Ban Status changed to: {user.is_banned}"
    else:
        return
        
    await chat_service._session.commit()
    await callback.answer(msg, show_alert=True)
    await callback.message.edit_reply_markup(
        reply_markup=get_admin_user_keyboard(user.telegram_id, user.is_vip, user.is_banned, current_page)
    )

@admin_router.message(Command("makepromo"))
async def cmd_make_promo(message: Message, command: CommandObject, chat_service: ChatService):
    """Admin command to create promo code. Usage: /makepromo LAUNCH 5 150 24"""
    from datetime import datetime, timezone, timedelta
    from app.db.models.user import PromoCode
    
    try:
        args = command.args.split()
        code = args[0].upper()
        vip_days = int(args[1])
        credits = int(args[2])
        hours_valid = int(args[3])
        
        expires = datetime.now(timezone.utc) + timedelta(hours=hours_valid)
        
        db_session = chat_service._session
        new_promo = PromoCode(code=code, vip_days=vip_days, credits=credits, expires_at=expires)
        db_session.add(new_promo)
        await db_session.commit()
        
        await message.answer(
            f"✅ <b>Promo Code Created!</b>\n\n"
            f"🎟 <b>Code:</b> <code>{code}</code>\n"
            f"👑 <b>VIP Days:</b> {vip_days}\n"
            f"💰 <b>Credits:</b> {credits}\n"
            f"⏱ <b>Expires In:</b> {hours_valid} hours",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer("⚠️ Usage: `/makepromo <CODE> <VIP_DAYS> <CREDITS> <HOURS>`\nExample: `/makepromo LAUNCH24 5 150 24`", parse_mode="Markdown")
