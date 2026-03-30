from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_profile_keyboard(user) -> InlineKeyboardMarkup:
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    toggle_text = "Switch to Pro" if current_model == "FLASH" else "Switch to Flash-Lite"

    if user.keep_chat_history:
        memory_text = "Memory: ON (Extended)" if user.has_active_vip else "Memory: ON (Limited)"
    else:
        memory_text = "Memory: Auto-Clear"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Purchase VIP", callback_data="upgrade_vip")],
            [InlineKeyboardButton(text="Daily Reward", callback_data="claim_daily_reward")],
            [InlineKeyboardButton(text="My Chat History", callback_data="view_chat_history")],
            [InlineKeyboardButton(text=toggle_text, callback_data="toggle_model")],
            [InlineKeyboardButton(text=memory_text, callback_data="toggle_memory")],
            [InlineKeyboardButton(text="Redeem Code", callback_data="redeem_promo_code")],
        ]
    )


def get_cancel_promo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Cancel", callback_data="cancel_promo_action")]]
    )


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Cancel", callback_data="cancel_action")]]
    )


def get_vip_plans_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Starter Pack ($1.99)", callback_data="buy_plan_starter")],
            [InlineKeyboardButton(text="Popular Pack ($6.99)", callback_data="buy_plan_popular")],
            [InlineKeyboardButton(text="Pro Pack ($14.99)", callback_data="buy_plan_pro")],
            [InlineKeyboardButton(text="Cancel", callback_data="cancel_action")],
        ]
    )
