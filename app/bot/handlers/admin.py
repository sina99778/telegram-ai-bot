import logging
import html
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from app.services.admin.admin_service import AdminService
from app.bot.middlewares.admin_filter import IsAdminFilter

# SECURE THE ENTIRE ROUTER IMPLICITLY
admin_router = Router()
admin_router.message.filter(IsAdminFilter())

logger = logging.getLogger(__name__)

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

@admin_router.message(Command("user_info"))
async def cmd_user_info(message: Message, command: CommandObject, admin_service: AdminService):
    if not command.args:
        return await message.reply("Usage: <code>/user_info <telegram_id></code>", parse_mode="HTML")
        
    try:
        target_id = int(command.args.strip())
        user = await admin_service.get_user_details(target_id)
        
        # 6. Escape attributes actively defending rendering breaks
        plan = html.escape(user.subscription_plan or 'None')
        name = html.escape(user.username or 'No Username')
        
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
        await message.reply("⚠️ Unknown error resolving explicitly targeting user data.")

@admin_router.message(Command("ledger"))
async def cmd_ledger(message: Message, command: CommandObject, admin_service: AdminService):
    """Admin command mapping direct structured views into identical internal financial audits."""
    if not command.args:
        return await message.reply("Usage: <code>/ledger <telegram_id></code>", parse_mode="HTML")
        
    try:
        target_id = int(command.args.strip())
        # Constrain limits robustly (Correction 6)
        records = await admin_service.get_user_ledger(target_id, limit=8) 
        
        if not records:
            return await message.reply("No ledger entries found strictly binding for this user.")
            
        text = f"🧾 <b>Recent Ledger for <code>{target_id}</code>:</b>\n\n"
        for r in records:
            sign = "+" if r.amount > 0 else ""
            desc = html.escape(r.description or "No context logged")
            # Limit description widths cleanly
            if len(desc) > 35:
                desc = desc[:32] + "..."
            
            text += f"🔹 <b>{r.type.name}</b>: {sign}{r.amount} (Bal: {r.balance_after})\n└ <i>{desc}</i>\n\n"
            
        await message.reply(text, parse_mode="HTML")
    except ValueError as e:
        await message.reply(f"❌ {html.escape(str(e))}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ledger query universally failed: {e}")
        await message.reply("⚠️ Fatal error resolving internal records.")
