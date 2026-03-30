from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Main admin control-center keyboard (Persian UI)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 آمار کل", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 لیست کاربران", callback_data="admin_users_list")],
        [InlineKeyboardButton(text="💰 مدیریت موجودی", callback_data="admin_manage_credits")],
        [InlineKeyboardButton(text="🚫 بن/آنبن", callback_data="admin_ban_user")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="start_over")],
    ])


def get_back_to_admin_kb() -> InlineKeyboardMarkup:
    """Single 'Back' button that returns to the admin main menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_main")],
    ])
