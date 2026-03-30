"""
Admin handler module.

All routes are gated by checking user.is_admin or settings.ADMIN_IDS.
Uses the existing DbSessionMiddleware's `session` and `chat_service` injection.
FSM is used for the multi-step "Gift Credits" flow.
"""

import logging
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.bot.keyboards.admin_kb import get_admin_main_kb, get_back_to_admin_kb
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

admin_router = Router(name="admin")


# ── FSM States for Gift Flow ─────────────────
class GiftCreditsStates(StatesGroup):
    waiting_for_telegram_id = State()
    waiting_for_amount = State()


class BanUserStates(StatesGroup):
    waiting_for_telegram_id = State()


# ── Helper: Admin check ──────────────────────
def _is_admin(user_id: int) -> bool:
    """Check against settings + DB. Settings takes priority."""
    return user_id in settings.admin_ids_list


# ────────────────────────────────────────────────
# /admin  –  Entry point
# ────────────────────────────────────────────────
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession):
    if not _is_admin(message.from_user.id):
        return  # Silently ignore non-admins

    await message.answer(
        "🛡️ <b>پنل مدیریت</b>\n\n"
        "به پنل کنترل خوش آمدید. یکی از گزینه‌ها را انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(),
    )


# ────────────────────────────────────────────────
# Callback: admin_main — Return to admin menu
# ────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_main")
async def cb_admin_main(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)

    # Clear any active FSM state
    await state.clear()

    await callback.message.edit_text(
        "🛡️ <b>پنل مدیریت</b>\n\n"
        "یکی از گزینه‌ها را انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(),
    )
    await callback.answer()


# ────────────────────────────────────────────────
# Callback: admin_stats — System-wide statistics
# ────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery, session: AsyncSession):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)

    try:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        total_credits = await session.scalar(select(func.sum(User.credit_balance))) or 0
        total_normal = await session.scalar(select(func.sum(User.normal_credits))) or 0
        total_premium = await session.scalar(select(func.sum(User.premium_credits))) or 0
        total_vip = await session.scalar(
            select(func.count(User.id)).where(User.is_vip == True)
        ) or 0

        # Users registered today
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_users = await session.scalar(
            select(func.count(User.id)).where(User.created_at >= today_start)
        ) or 0

        text = (
            "📊 <b>آمار سیستم</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥  <b>کل کاربران:</b>  {total_users}\n"
            f"🆕  <b>ثبت‌نام امروز:</b>  {today_users}\n"
            f"👑  <b>کاربران VIP:</b>  {total_vip}\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"💬  <b>مجموع اعتبار عادی:</b>  <code>{total_normal:,}</code>\n"
            f"🪙  <b>مجموع اعتبار ویژه:</b>  <code>{total_premium:,}</code>\n"
            f"💰  <b>مجموع بالانس:</b>  <code>{total_credits:,}</code>\n"
        )
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_back_to_admin_kb(),
        )
    except Exception as e:
        logger.error(f"Admin stats error: {e}", exc_info=True)
        await callback.message.edit_text(
            "⚠️ خطا در دریافت آمار. لاگ‌ها را بررسی کنید.",
            reply_markup=get_back_to_admin_kb(),
        )
    await callback.answer()


# ────────────────────────────────────────────────
# Callback: admin_users_list — Latest registered users
# ────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_users_list")
async def cb_admin_users_list(callback: CallbackQuery, chat_service: ChatService):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)

    try:
        users = await chat_service._repo.get_users_paginated(limit=10, offset=0)
        if not users:
            return await callback.message.edit_text(
                "هیچ کاربری یافت نشد.",
                reply_markup=get_back_to_admin_kb(),
            )

        text = "👥 <b>آخرین کاربران ثبت‌نام شده:</b>\n\n"
        for i, u in enumerate(users, 1):
            name = u.first_name or u.username or "—"
            vip_badge = " 👑" if u.is_vip else ""
            banned_badge = " 🚫" if u.is_banned else ""
            text += (
                f"{i}. <code>{u.telegram_id}</code> | "
                f"{name}{vip_badge}{banned_badge}\n"
                f"   💬 {u.normal_credits}  🪙 {u.premium_credits}\n"
            )

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_back_to_admin_kb(),
        )
    except Exception as e:
        logger.error(f"Admin users list error: {e}", exc_info=True)
        await callback.message.edit_text(
            "⚠️ خطا در دریافت لیست کاربران.",
            reply_markup=get_back_to_admin_kb(),
        )
    await callback.answer()


# ────────────────────────────────────────────────
# Gift Credits — FSM Flow
# ────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_manage_credits")
async def cb_gift_start(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)

    await state.set_state(GiftCreditsStates.waiting_for_telegram_id)
    await callback.message.edit_text(
        "💰 <b>مدیریت موجودی</b>\n\n"
        "لطفاً <b>شناسه تلگرام</b> (Telegram ID) کاربر مورد نظر را ارسال کنید:",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(),
    )
    await callback.answer()


@admin_router.message(GiftCreditsStates.waiting_for_telegram_id)
async def gift_receive_tg_id(message: Message, state: FSMContext, chat_service: ChatService):
    if not _is_admin(message.from_user.id):
        return

    try:
        target_id = int(message.text.strip())
    except (ValueError, AttributeError):
        return await message.answer("❌ لطفاً یک عدد معتبر (شناسه تلگرام) وارد کنید.")

    # Verify user exists
    user = await chat_service._repo.get_user_by_telegram_id(target_id)
    if not user:
        return await message.answer(
            f"❌ کاربری با شناسه <code>{target_id}</code> یافت نشد.",
            parse_mode="HTML",
        )

    await state.update_data(target_telegram_id=target_id, target_name=user.first_name or "—")
    await state.set_state(GiftCreditsStates.waiting_for_amount)
    await message.answer(
        f"✅ کاربر: <b>{user.first_name or '—'}</b> (<code>{target_id}</code>)\n"
        f"موجودی فعلی: 💬 {user.normal_credits} | 🪙 {user.premium_credits}\n\n"
        "حالا <b>تعداد اعتبار ویژه</b> (Premium Credits) برای افزودن را وارد کنید:\n"
        "<i>(عدد منفی برای کسر)</i>",
        parse_mode="HTML",
    )


@admin_router.message(GiftCreditsStates.waiting_for_amount)
async def gift_receive_amount(message: Message, state: FSMContext, session: AsyncSession):
    if not _is_admin(message.from_user.id):
        return

    try:
        amount = int(message.text.strip())
    except (ValueError, AttributeError):
        return await message.answer("❌ لطفاً یک عدد معتبر وارد کنید.")

    data = await state.get_data()
    target_id = data["target_telegram_id"]
    target_name = data["target_name"]

    # Fetch and update
    user = await session.scalar(
        select(User).where(User.telegram_id == target_id)
    )
    if not user:
        await state.clear()
        return await message.answer("❌ کاربر یافت نشد. عملیات لغو شد.")

    user.premium_credits += amount
    if user.premium_credits < 0:
        user.premium_credits = 0
    await session.commit()

    sign = "+" if amount >= 0 else ""
    await message.answer(
        f"✅ <b>عملیات موفق</b>\n\n"
        f"کاربر: <b>{target_name}</b> (<code>{target_id}</code>)\n"
        f"تغییر: <code>{sign}{amount}</code> اعتبار ویژه\n"
        f"موجودی جدید: 🪙 <code>{user.premium_credits}</code>",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(),
    )
    await state.clear()


# ────────────────────────────────────────────────
# Ban / Unban — FSM Flow
# ────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_ban_user")
async def cb_ban_start(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔️ دسترسی ندارید", show_alert=True)

    await state.set_state(BanUserStates.waiting_for_telegram_id)
    await callback.message.edit_text(
        "🚫 <b>بن / آنبن کاربر</b>\n\n"
        "لطفاً <b>شناسه تلگرام</b> کاربر مورد نظر را ارسال کنید.\n"
        "وضعیت بن کاربر <b>تغییر</b> (toggle) خواهد کرد.",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(),
    )
    await callback.answer()


@admin_router.message(BanUserStates.waiting_for_telegram_id)
async def ban_receive_tg_id(message: Message, state: FSMContext, session: AsyncSession):
    if not _is_admin(message.from_user.id):
        return

    try:
        target_id = int(message.text.strip())
    except (ValueError, AttributeError):
        return await message.answer("❌ لطفاً یک عدد معتبر (شناسه تلگرام) وارد کنید.")

    user = await session.scalar(
        select(User).where(User.telegram_id == target_id)
    )
    if not user:
        await state.clear()
        return await message.answer(
            f"❌ کاربری با شناسه <code>{target_id}</code> یافت نشد.",
            parse_mode="HTML",
        )

    # Toggle ban status
    user.is_banned = not user.is_banned
    await session.commit()

    status_text = "🚫 بن شد" if user.is_banned else "✅ آنبن شد"
    await message.answer(
        f"{status_text}\n\n"
        f"کاربر: <b>{user.first_name or '—'}</b> (<code>{target_id}</code>)\n"
        f"وضعیت فعلی: <b>{'بن‌شده ⛔️' if user.is_banned else 'فعال ✅'}</b>",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(),
    )
    await state.clear()


# ────────────────────────────────────────────────
# /stats — Quick command shortcut (kept for CLI admins)
# ────────────────────────────────────────────────
@admin_router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession):
    if not _is_admin(message.from_user.id):
        return

    total_users = await session.scalar(select(func.count(User.id))) or 0
    total_credits = await session.scalar(select(func.sum(User.credit_balance))) or 0

    await message.reply(
        f"📊 <b>آمار سریع</b>\n\n"
        f"👥 کل کاربران: {total_users}\n"
        f"💰 مجموع بالانس: <code>{total_credits:,}</code>",
        parse_mode="HTML",
    )


# ────────────────────────────────────────────────
# /gift <telegram_id> <amount> — Quick CLI gift
# ────────────────────────────────────────────────
@admin_router.message(Command("gift"))
async def cmd_gift(message: Message, command: CommandObject, session: AsyncSession):
    if not _is_admin(message.from_user.id):
        return

    if not command.args:
        return await message.reply(
            "Usage: <code>/gift &lt;telegram_id&gt; &lt;amount&gt;</code>",
            parse_mode="HTML",
        )

    parts = command.args.strip().split()
    if len(parts) != 2:
        return await message.reply(
            "Usage: <code>/gift &lt;telegram_id&gt; &lt;amount&gt;</code>",
            parse_mode="HTML",
        )

    try:
        target_id = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        return await message.reply("❌ پارامترها باید عدد باشند.")

    user = await session.scalar(
        select(User).where(User.telegram_id == target_id)
    )
    if not user:
        return await message.reply(
            f"❌ کاربری با شناسه <code>{target_id}</code> یافت نشد.",
            parse_mode="HTML",
        )

    user.premium_credits += amount
    if user.premium_credits < 0:
        user.premium_credits = 0
    await session.commit()

    sign = "+" if amount >= 0 else ""
    await message.reply(
        f"✅ <code>{sign}{amount}</code> اعتبار ویژه به <code>{target_id}</code> اضافه شد.\n"
        f"موجودی جدید: 🪙 <code>{user.premium_credits}</code>",
        parse_mode="HTML",
    )
