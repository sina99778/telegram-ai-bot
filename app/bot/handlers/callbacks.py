from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from app.services.payment_service import NowPaymentsService

logger = logging.getLogger(__name__)
callback_router = Router(name="callbacks")
from app.services.chat_service import ChatService

@callback_router.callback_query(F.data == "toggle_model")
async def cq_toggle_model(callback: CallbackQuery, chat_service: ChatService) -> None:
    """Toggles the user's preferred AI model and updates the profile message inline."""
    if callback.from_user is None or callback.message is None:
        return

    # 1. Fetch user from DB
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("User not found.", show_alert=True)
        return

    # 2. Toggle the model
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "PRO"
    new_model = "PRO" if current_model == "FLASH" else "FLASH"
    
    # Prevent non-VIP users from switching to PRO via the button
    if new_model == "PRO" and not user.is_vip:
        await callback.answer("👑 PRO model is for VIP members only!", show_alert=True)
        return

    user.preferred_text_model = new_model
    await chat_service._session.commit()

    # 3. Regenerate Profile Text
    plan_name = "👑 VIP Premium" if user.is_vip else "🆓 Free Tier"
    expire_text = f"\n📅 <b>Expires:</b> {user.vip_expire_date.strftime('%Y-%m-%d')}" if user.vip_expire_date else ""

    text = (
        f"👤 <b>User Profile</b>\n\n"
        f"<b>Name:</b> {user.first_name}\n"
        f"<b>ID:</b> <code>{user.telegram_id}</code>\n\n"
        f"🏷️ <b>Current Plan:</b> {plan_name}{expire_text}\n"
        f"💬 <b>Normal Credits:</b> {user.normal_credits} <i>(Free Daily)</i>\n"
        f"🪙 <b>Premium Credits:</b> {user.premium_credits} <i>(Images / Pro Chat)</i>\n\n"
        f"⚙️ <b>Preferred Text Model:</b>\n<b>{new_model}</b>"
    )

    if not user.is_vip:
        text += f"\n\n<i>Upgrade to VIP to access unlimited features!</i>"

    # 4. Edit the message inline (No new message sent!)
    from app.bot.keyboards.inline import get_profile_keyboard
    
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=get_profile_keyboard(user),
            parse_mode="HTML"
        )
    except Exception:
        pass # Ignore errors if the text is exactly the same
    
    # Show a small toast notification at the top of the user's screen
    await callback.answer(f"✅ Model switched to {new_model}!")

@callback_router.callback_query(F.data == "upgrade_vip")
async def cq_upgrade_vip(callback: CallbackQuery) -> None:
    """Generate a NowPayments invoice and send the link to the user."""
    await callback.message.edit_text("⏳ Generating your secure payment link...", parse_mode="HTML")
    
    # Updated Price: $2.00
    invoice_url = await NowPaymentsService.create_invoice(telegram_id=callback.from_user.id, price_usd=2.0)
    
    if invoice_url:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Pay with Crypto", url=invoice_url)],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
        ])
        await callback.message.edit_text(
            "💎 <b>VIP Premium Subscription</b>\n\n"
            "Price: <b>$2.00</b>\n"
            "Reward: <b>VIP Status + 100 Premium Credits</b>\n"
            "Payment Method: <b>Crypto (USDT, TRX, TON, etc.)</b>\n\n"
            "Click the button below to complete your payment.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text("⚠️ Sorry, the payment gateway is currently unavailable.")

@callback_router.callback_query(F.data == "check_stats")
async def cq_check_stats(callback: CallbackQuery) -> None:
    """Handle the stats inline button click."""
    await callback.answer("Fetching your usage stats...", show_alert=False)
    await callback.message.answer("📊 You have used <b>0</b> out of <b>15</b> free requests today.", parse_mode="HTML")

@callback_router.callback_query(F.data == "cancel_action")
async def cq_cancel(callback: CallbackQuery) -> None:
    """Handle universal cancel."""
    await callback.message.delete()
    await callback.answer("Action canceled.")
