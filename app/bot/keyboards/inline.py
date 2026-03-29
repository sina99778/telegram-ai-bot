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

def get_vip_plans_keyboard() -> InlineKeyboardMarkup:
    """Returns the keyboard with the 3 new premium plans."""
    keyboard = [
        [InlineKeyboardButton(text="💳 Starter Pack ($1.99)", callback_data="buy_plan_starter")],
        [InlineKeyboardButton(text="🔥 Popular Pack ($6.99)", callback_data="buy_plan_popular")],
        [InlineKeyboardButton(text="👑 Pro Pack ($14.99)", callback_data="buy_plan_pro")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Returns inline buttons for the Admin Panel."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 View Bot Stats", callback_data="admin_stats")],
            [InlineKeyboardButton(text="❌ Close Panel", callback_data="cancel_action")]
        ]
    )

def get_admin_user_keyboard(user_id: int, is_vip: bool, is_banned: bool) -> InlineKeyboardMarkup:
    vip_text = "❌ Remove VIP" if is_vip else "👑 Make VIP"
    ban_text = "✅ Unban User" if is_banned else "🚫 Ban User"
    
    keyboard = [
        [InlineKeyboardButton(text="➕ Add 50 Premium Credits", callback_data=f"adm_cred_{user_id}")],
        [
            InlineKeyboardButton(text=vip_text, callback_data=f"adm_vip_{user_id}"),
            InlineKeyboardButton(text=ban_text, callback_data=f"adm_ban_{user_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
