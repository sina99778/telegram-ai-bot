from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Main admin control-center keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistics", callback_data="admin_stats"),
            InlineKeyboardButton(text="👥 Manage Users", callback_data="admin_users"),
        ],
        [
            InlineKeyboardButton(text="💰 Gift Credits", callback_data="admin_gift"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="admin_settings"),
        ],
    ])


def get_back_to_admin_kb() -> InlineKeyboardMarkup:
    """Single 'Back' button that returns to the admin main menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="admin_main")],
    ])
