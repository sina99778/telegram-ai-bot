from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from app.services.payment_service import NowPaymentsService

logger = logging.getLogger(__name__)
callback_router = Router(name="callbacks")

@callback_router.callback_query(F.data == "upgrade_vip")
async def cq_upgrade_vip(callback: CallbackQuery) -> None:
    """Generate a NowPayments invoice and send the link to the user."""
    await callback.message.edit_text("⏳ Generating your secure payment link...", parse_mode="HTML")
    
    # Let's set the VIP price to $5.00 for example
    invoice_url = await NowPaymentsService.create_invoice(telegram_id=callback.from_user.id, price_usd=5.0)
    
    if invoice_url:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Pay with Crypto (NowPayments)", url=invoice_url)],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
        ])
        await callback.message.edit_text(
            "💎 <b>VIP Premium Subscription</b>\n\n"
            "Price: <b>$5.00</b>\n"
            "Payment Method: <b>Crypto (USDT, TRX, TON, etc.)</b>\n\n"
            "Click the button below to complete your payment. Your account will be upgraded automatically within a few minutes after the transaction is confirmed.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text("⚠️ Sorry, the payment gateway is currently unavailable. Please try again later.")

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
