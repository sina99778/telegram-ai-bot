from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.db.models import User

def get_profile_keyboard(user: User) -> InlineKeyboardMarkup:
    """Returns profile/settings keyboard with dynamic model switching buttons."""
    # Determine the current active model for the button text
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "PRO"
    toggle_text = "🔄 Active Model: Flash (Free)" if current_model == "FLASH" else "🔄 Active Model: PRO (Paid)"
    
    buttons = [
        [InlineKeyboardButton(text="💎 Purchase VIP", callback_data="upgrade_vip")],
        [InlineKeyboardButton(text=toggle_text, callback_data="toggle_model")]
    ]
    
    if user.is_vip:
        buttons.append([InlineKeyboardButton(text="👨‍💻 Admin Panel", callback_data="admin_stats")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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
