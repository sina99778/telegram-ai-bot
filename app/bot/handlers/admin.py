"""
Admin handler module.

All routes in this router are gated by IsAdminFilter, which checks
settings.admin_ids_list for both Message and CallbackQuery events.
"""

import logging
import html

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery

from app.bot.middlewares.admin_filter import IsAdminFilter
from app.bot.keyboards.admin_kb import get_admin_main_kb, get_back_to_admin_kb
from app.services.admin.admin_service import AdminService

# ── Router Setup ────────────────────────────────────
admin_router = Router()

# Gate both message and callback_query events
admin_router.message.filter(IsAdminFilter())
admin_router.callback_query.filter(IsAdminFilter())

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────
# /admin  –  Entry point
# ────────────────────────────────────────────────────
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Send the main admin panel."""
    await message.answer(
        "🛡️ <b>Welcome to the Control Center, Boss!</b>\n\n"
        "Select an option below to manage the platform.",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(),
    )


# ────────────────────────────────────────────────────
# Callback: admin_main  –  Return to the main menu
# ────────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_main")
async def cb_admin_main(callback: CallbackQuery):
    """Edit the current message back to the main admin menu."""
    await callback.message.edit_text(
        "🛡️ <b>Welcome to the Control Center, Boss!</b>\n\n"
        "Select an option below to manage the platform.",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(),
    )
    await callback.answer()


# ────────────────────────────────────────────────────
# Callback: admin_stats  –  System-wide statistics
# ────────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery, admin_service: AdminService):
    """Display aggregated platform metrics."""
    try:
        stats = await admin_service.get_system_stats()
        text = (
            "📊 <b>Platform Statistics</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥  <b>Total Users:</b>  {stats['total_users']}\n"
            f"🟢  <b>Active Users:</b>  {stats['total_active_users']}\n"
            f"💎  <b>Premium Users:</b>  {stats['total_premium']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙  <b>Credits in Circulation:</b>  <code>{stats['total_credits_circulation']:,}</code>\n"
            f"🔥  <b>Credits Consumed:</b>  <code>{stats['total_lifetime_used']:,}</code>\n"
            f"💸  <b>Credits Purchased:</b>  <code>{stats['total_lifetime_purchased']:,}</code>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅  <b>Payments Completed:</b>  {stats['total_payments_completed']}\n"
            f"❌  <b>Payments Failed:</b>  {stats['total_payments_failed']}"
        )
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_back_to_admin_kb(),
        )
    except Exception as e:
        logger.error(f"Failed to fetch admin stats: {e}", exc_info=True)
        await callback.message.edit_text(
            "⚠️ Could not retrieve statistics. Check the logs.",
            reply_markup=get_back_to_admin_kb(),
        )
    await callback.answer()


# ────────────────────────────────────────────────────
# Callback: admin_users  –  User lookup
# ────────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_users")
async def cb_admin_users(callback: CallbackQuery):
    """Prompt the admin for a Telegram ID to look up."""
    await callback.message.edit_text(
        "👥 <b>Manage Users</b>\n\n"
        "Send <code>/user_info &lt;telegram_id&gt;</code> to view a user.\n"
        "Send <code>/ledger &lt;telegram_id&gt;</code> to view their credit ledger.",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(),
    )
    await callback.answer()


# ────────────────────────────────────────────────────
# Callback: admin_gift  –  Credit gifting instructions
# ────────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_gift")
async def cb_admin_gift(callback: CallbackQuery):
    """Prompt the admin for gift command usage."""
    await callback.message.edit_text(
        "💰 <b>Gift Credits</b>\n\n"
        "Send <code>/gift &lt;telegram_id&gt; &lt;amount&gt;</code> to add credits to a user.",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(),
    )
    await callback.answer()


# ────────────────────────────────────────────────────
# Callback: admin_settings  –  Feature pricing
# ────────────────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    """Prompt the admin for settings commands."""
    await callback.message.edit_text(
        "⚙️ <b>Settings</b>\n\n"
        "Send <code>/set_price &lt;feature_name&gt; &lt;cost&gt;</code> to update a feature's credit cost.",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(),
    )
    await callback.answer()


# ────────────────────────────────────────────────────
# /stats  –  Quick command shortcut (kept for CLI admins)
# ────────────────────────────────────────────────────
@admin_router.message(Command("stats"))
async def cmd_stats(message: Message, admin_service: AdminService):
    stats = await admin_service.get_system_stats()
    text = (
        "📊 <b>System Statistics</b>\n\n"
        f"👥 Total Users: {stats['total_users']} (Active: {stats['total_active_users']})\n"
        f"💎 Premium Users: {stats['total_premium']}\n\n"
        f"🪙 Credits Floating: <code>{stats['total_credits_circulation']:,}</code>\n"
        f"🔥 Credits Used: <code>{stats['total_lifetime_used']:,}</code>\n"
        f"💸 Credits Purchased: <code>{stats['total_lifetime_purchased']:,}</code>\n\n"
        f"💳 Payments Ok: {stats['total_payments_completed']}\n"
        f"❌ Payments Fail: {stats['total_payments_failed']}"
    )
    await message.reply(text, parse_mode="HTML")


# ────────────────────────────────────────────────────
# /user_info <telegram_id>
# ────────────────────────────────────────────────────
@admin_router.message(Command("user_info"))
async def cmd_user_info(message: Message, command: CommandObject, admin_service: AdminService):
    if not command.args:
        return await message.reply("Usage: <code>/user_info &lt;telegram_id&gt;</code>", parse_mode="HTML")

    try:
        target_id = int(command.args.strip())
        user = await admin_service.get_user_details(target_id)

        plan = html.escape(user.subscription_plan or "None")
        name = html.escape(user.username or "No Username")

        text = (
            f"👤 <b>User Info:</b> <code>{user.telegram_id}</code> (@{name})\n"
            f"💰 <b>Balance:</b> {user.credit_balance:,}\n"
            f"📈 <b>Lifetime Bought:</b> {user.lifetime_credits_purchased:,}\n"
            f"📉 <b>Lifetime Used:</b> {user.lifetime_credits_used:,}\n"
            f"🏷️ <b>Plan:</b> {plan}\n"
            f"💎 <b>Premium:</b> {'Yes' if user.is_premium else 'No'}"
        )
        await message.reply(text, parse_mode="HTML")
    except ValueError as e:
        await message.reply(f"❌ {html.escape(str(e))}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"User Info query error: {e}")
        await message.reply("⚠️ Could not retrieve user information.")


# ────────────────────────────────────────────────────
# /ledger <telegram_id>
# ────────────────────────────────────────────────────
@admin_router.message(Command("ledger"))
async def cmd_ledger(message: Message, command: CommandObject, admin_service: AdminService):
    if not command.args:
        return await message.reply("Usage: <code>/ledger &lt;telegram_id&gt;</code>", parse_mode="HTML")

    try:
        target_id = int(command.args.strip())
        records = await admin_service.get_user_ledger(target_id, limit=8)

        if not records:
            return await message.reply("No ledger entries found for this user.")

        text = f"🧾 <b>Recent Ledger for <code>{target_id}</code>:</b>\n\n"
        for r in records:
            sign = "+" if r.amount > 0 else ""
            desc = html.escape(r.description or "—")
            if len(desc) > 35:
                desc = desc[:32] + "…"
            text += (
                f"🔹 <b>{r.type.name}</b>: {sign}{r.amount} "
                f"(Bal: {r.balance_after})\n"
                f"   └ <i>{desc}</i>\n\n"
            )
        await message.reply(text, parse_mode="HTML")
    except ValueError as e:
        await message.reply(f"❌ {html.escape(str(e))}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ledger query failed: {e}")
        await message.reply("⚠️ Could not retrieve ledger records.")


# ────────────────────────────────────────────────────
# /gift <telegram_id> <amount>
# ────────────────────────────────────────────────────
@admin_router.message(Command("gift"))
async def cmd_gift(message: Message, command: CommandObject, admin_service: AdminService):
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
        if amount <= 0:
            return await message.reply("❌ Amount must be a positive integer.")

        new_balance = await admin_service.add_credits_to_user(
            admin_telegram_id=message.from_user.id,
            target_telegram_id=target_id,
            amount=amount,
        )
        await message.reply(
            f"✅ Gifted <b>{amount:,}</b> credits to <code>{target_id}</code>.\n"
            f"Their new balance: <code>{new_balance:,}</code>",
            parse_mode="HTML",
        )
    except ValueError as e:
        await message.reply(f"❌ {html.escape(str(e))}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Gift credits error: {e}", exc_info=True)
        await message.reply("⚠️ Could not gift credits. Check the logs.")


# ────────────────────────────────────────────────────
# /set_price <feature_name> <cost>
# ────────────────────────────────────────────────────
@admin_router.message(Command("set_price"))
async def cmd_set_price(message: Message, command: CommandObject, admin_service: AdminService):
    if not command.args:
        return await message.reply(
            "Usage: <code>/set_price &lt;feature_name&gt; &lt;cost&gt;</code>",
            parse_mode="HTML",
        )

    parts = command.args.strip().split()
    if len(parts) != 2:
        return await message.reply(
            "Usage: <code>/set_price &lt;feature_name&gt; &lt;cost&gt;</code>",
            parse_mode="HTML",
        )

    try:
        from app.core.enums import FeatureName
        feature_name = FeatureName(parts[0])
        new_cost = int(parts[1])
        if new_cost < 0:
            return await message.reply("❌ Cost cannot be negative.")

        await admin_service.update_feature_price(feature_name, new_cost)
        await message.reply(
            f"✅ <b>{feature_name.value}</b> cost updated to <code>{new_cost}</code> credits.",
            parse_mode="HTML",
        )
    except ValueError as e:
        await message.reply(f"❌ Invalid feature name or cost: {html.escape(str(e))}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Set price error: {e}", exc_info=True)
        await message.reply("⚠️ Could not update feature price. Check the logs.")
