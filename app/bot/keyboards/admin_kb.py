from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Main admin control-center keyboard (Persian UI)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 آمار کل", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 مدیریت کاربران", callback_data="admin_users_list")],
        [InlineKeyboardButton(text="📣 پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="admin_settings")],
    ])


def get_user_manage_kb(user_id: int) -> InlineKeyboardMarkup:
    """Keyboard for managing a specific user."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 افزایش اعتبار", callback_data=f"admin_user_add_credit:{user_id}")],
        [InlineKeyboardButton(text="🚫 بن/آنبن", callback_data=f"admin_user_toggle_ban:{user_id}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_users_list")],
    ])


def get_back_to_admin_kb() -> InlineKeyboardMarkup:
    """Single 'Back' button that returns to the admin main menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_main")],
    ])
