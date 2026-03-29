from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_profile_keyboard(user_is_vip: bool, current_model: str) -> InlineKeyboardMarkup:
    """Returns profile/settings keyboard with dynamic model switching buttons."""
    # Logic to define button text based on current model preference
    model_btn_text = "🔄 Active Model: Flash (Free)" if current_model == 'flash' else "🔄 Active Model: Pro (Paid)"
    
    buttons = [
        [InlineKeyboardButton(text="💎 Purchase VIP", callback_data="upgrade_vip")],
        [InlineKeyboardButton(text=model_btn_text, callback_data="switch_text_model")]
    ]
    
    if user_is_vip:
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
