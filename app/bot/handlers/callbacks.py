from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)
callback_router = Router(name="callbacks")

@callback_router.callback_query(F.data == "upgrade_vip")
async def cq_upgrade_vip(callback: CallbackQuery) -> None:
    """Handle the VIP upgrade inline button click."""
    await callback.answer("Redirecting to payment system...", show_alert=False)
    await callback.message.answer("💳 <i>Payment gateway integration is scheduled for Phase 4! Stay tuned.</i>", parse_mode="HTML")

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
