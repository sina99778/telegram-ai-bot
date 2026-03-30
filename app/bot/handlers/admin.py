"""
Admin handler module.

All routes are gated by checking user.is_admin = True from the database.
Uses the existing DbSessionMiddleware's `session` and `chat_service` injection.
FSM is used for the multi-step "Add Credits" and "Broadcast" flows.
"""

import logging
import asyncio
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.bot.keyboards.admin_kb import get_admin_main_kb, get_back_to_admin_kb, get_user_manage_kb
from app.services.billing.billing_service import BillingService
from app.core.enums import LedgerEntryType
import uuid

logger = logging.getLogger(__name__)

admin_router = Router(name="admin")

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_user_id = State()
    waiting_for_amount = State()

async def _is_admin(user_id: int, session: AsyncSession) -> bool:
    """Strictly allowed only for users where user.is_admin is True."""
    user = await session.scalar(select(User).where(User.telegram_id == user_id))
    return bool(user and user.is_admin)

@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return

    await state.clear()
    await message.answer(
        "🛡️ <b>پنل مدیریت</b>\n\n"
        "به پنل کنترل خوش آمدید. یکی از گزینه‌ها را انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(),
    )


@admin_router.callback_query(F.data == "admin_main")
async def cb_admin_main(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)

    await state.clear()
    await callback.message.edit_text(
        "🛡️ <b>پنل مدیریت</b>\n\n"
        "یکی از گزینه‌ها را انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(),
    )
    await callback.answer()

@admin_router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)

    try:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        total_credits = await session.scalar(select(func.sum(User.credit_balance))) or 0

        # Users registered today
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_users = await session.scalar(
            select(func.count(User.id)).where(User.created_at >= today_start)
        ) or 0

        text = (
            "📊 <b>آمار کل سیستم</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥  <b>کل کاربران:</b>  {total_users}\n"
            f"🆕  <b>ثبت‌نام امروز:</b>  {today_users}\n"
            f"💰  <b>مجموع اعتبار سیستم:</b>  <code>{total_credits:,}</code>\n"
        )
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_back_to_admin_kb(),
        )
    except Exception as e:
        logger.error(f"Admin stats error: {e}", exc_info=True)
        await callback.message.edit_text(
            "⚠️ خطا در دریافت آمار.",
            reply_markup=get_back_to_admin_kb(),
        )
    await callback.answer()

@admin_router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)
    
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.edit_text(
        "📣 <b>ارسال پیام همگانی</b>\n\n"
        "لطفاً پیام خود را ارسال کنید (متن، عکس، ویدیو و ...).\n"
        "برای لغو روی دکمه بازگشت کلیک کنید.",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb()
    )
    await callback.answer()

@admin_router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast_message(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    
    await state.clear()
    
    # Get all users
    stmt = select(User.telegram_id).where(User.telegram_id.is_not(None))
    result = await session.execute(stmt)
    user_ids = result.scalars().all()
    
    if not user_ids:
        return await message.answer("کاربری برای ارسال پیام یافت نشد.")

    status_msg = await message.answer(f"⏳ در حال ارسال پیام به {len(user_ids)} کاربر...\nلطفاً صبور باشید.")
    
    success_count = 0
    fail_count = 0

    for uid in user_ids:
        try:
            await message.send_copy(chat_id=uid)
            success_count += 1
        except Exception:
            fail_count += 1
        
        await asyncio.sleep(0.05) # 0.05s delay as requested

    await status_msg.edit_text(
        f"✅ <b>گزارش ارسال پیام همگانی:</b>\n\n"
        f"🎯 ارسال موفق: {success_count}\n"
        f"❌ ارسال ناموفق: {fail_count}\n"
        f"👥 کل کاربران: {len(user_ids)}",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb()
    )

# ── User Management Flow ────────────────────────

@admin_router.callback_query(F.data == "admin_users_list")
async def cb_user_management(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)
    
    await state.set_state(AdminStates.waiting_for_user_id)
    await callback.message.edit_text(
        "👥 <b>مدیریت کاربران</b>\n\n"
        "لطفاً شناسه تلگرام کاربر (Telegram ID) را وارد کنید:",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb()
    )
    await callback.answer()

@admin_router.message(AdminStates.waiting_for_user_id)
async def process_user_id(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return

    if not message.text or not message.text.lstrip('-').isdigit():
        return await message.answer("❌ لطفاً یک عدد معتبر (شناسه تلگرام) وارد کنید.")
        
    target_id = int(message.text.strip())

    user = await session.scalar(select(User).where(User.telegram_id == target_id))
    if not user:
        return await message.answer(
            f"❌ کاربری با شناسه <code>{target_id}</code> در دیتابیس یافت نشد.",
            parse_mode="HTML",
            reply_markup=get_back_to_admin_kb()
        )
    
    # Show info and actions
    name = user.first_name or user.username or "ناشناس"
    status = "بن‌شده ⛔️" if user.is_banned else "فعال ✅"
    text = (
        f"👤 <b>اطلاعات کاربر</b>\n"
        f"━━━━━━━━━━━\n"
        f"نام: {name}\n"
        f"آیدی: <code>{user.telegram_id}</code>\n"
        f"وضعیت: {status}\n"
        f"موجودی اعتبار: <code>{user.credit_balance:,}</code>\n\n"
        f"یک عملیات انتخاب کنید:"
    )

    # Clear state and show manage kb
    await state.clear()
    await message.answer(text, parse_mode="HTML", reply_markup=get_user_manage_kb(user.telegram_id))

@admin_router.callback_query(F.data.startswith("admin_user_add_credit:"))
async def cb_add_credit_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)
    
    user_id = int(callback.data.split(":")[1])
    
    await state.update_data(target_tg_id=user_id)
    await state.set_state(AdminStates.waiting_for_amount)
    
    await callback.message.edit_text(
        f"💰 <b>افزایش اعتبار</b>\n\n"
        f"لطفاً مقدار اعتباری که می‌خواهید به کاربر <code>{user_id}</code> اضافه کنید را وارد نمایید (به عدد):",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb()
    )
    await callback.answer()

@admin_router.message(AdminStates.waiting_for_amount)
async def process_add_credit_amount(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
        
    if not message.text or not message.text.lstrip('-').isdigit():
        return await message.answer("❌ لطفاً یک عدد معتبر وارد کنید.")
        
    amount = int(message.text.strip())
    
    data = await state.get_data()
    target_tg_id = data.get("target_tg_id")
    
    user = await session.scalar(select(User).where(User.telegram_id == target_tg_id))
    if not user:
        await state.clear()
        return await message.answer("❌ کاربر یافت نشد.", reply_markup=get_back_to_admin_kb())

    billing = BillingService(session)
    ref_id = f"admin_gift_{message.from_user.id}_{uuid.uuid4().hex[:6]}"
    
    try:
        await billing.add_credits(
            user_id=user.id,
            amount=amount,
            entry_type=LedgerEntryType.ADMIN_ADJUSTMENT,
            reference_type="admin_gift",
            reference_id=ref_id,
            description=f"Admin {message.from_user.id} gifted {amount} credits"
        )
        await session.commit()
        
        # refresh user for latest balance
        user = await session.scalar(select(User).where(User.telegram_id == target_tg_id))
        
        await message.answer(
            f"✅ با موفقیت {amount} اعتبار به کاربر <code>{target_tg_id}</code> اضافه شد.\n"
            f"موجودی جدید: <code>{user.credit_balance:,}</code>",
            parse_mode="HTML",
            reply_markup=get_user_manage_kb(target_tg_id)
        )
    except Exception as e:
        await session.rollback()
        logger.error(f"Gift amount error: {e}")
        await message.answer("⚠️ خطا در افزودن موجودی.", reply_markup=get_back_to_admin_kb())

    await state.clear()

@admin_router.callback_query(F.data.startswith("admin_user_toggle_ban:"))
async def cb_toggle_ban(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)
        
    user_id = int(callback.data.split(":")[1])
    
    user = await session.scalar(select(User).where(User.telegram_id == user_id))
    if not user:
        return await callback.answer("❌ کاربر یافت نشد.", show_alert=True)

    user.is_banned = not user.is_banned
    await session.commit()

    status_text = "🚫 بن شد" if user.is_banned else "✅ آنبن شد"
    
    await callback.message.edit_text(
        f"{status_text}\n\n"
        f"کاربر: <b>{user.first_name or 'ناشناس'}</b> (<code>{user_id}</code>)\n"
        f"وضعیت فعلی: <b>{'بن‌شده ⛔️' if user.is_banned else 'فعال ✅'}</b>",
        parse_mode="HTML",
        reply_markup=get_user_manage_kb(user_id)
    )
    await callback.answer()
