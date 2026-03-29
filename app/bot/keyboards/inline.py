from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_profile_keyboard() -> InlineKeyboardMarkup:
    """Returns inline buttons for the user profile."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Upgrade to VIP", callback_data="upgrade_vip")],
            [InlineKeyboardButton(text="📊 Check Usage Stats", callback_data="check_stats")]
        ]
    )

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Returns a universal cancel inline button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
        ]
    )

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Returns inline buttons for the Admin Panel."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 View Bot Stats", callback_data="admin_stats")],
            [InlineKeyboardButton(text="❌ Close Panel", callback_data="cancel_action")]
        ]
    )
