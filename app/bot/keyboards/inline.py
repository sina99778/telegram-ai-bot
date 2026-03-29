from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.db.models import User

def get_profile_keyboard(user) -> InlineKeyboardMarkup:
    """Returns the inline keyboard for the user profile."""
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "PRO"
    toggle_text = "🔄 Active Model: Flash" if current_model == "FLASH" else "🔄 Active Model: PRO"
    
    # Dynamic memory text based on VIP status
    if user.keep_chat_history:
        memory_text = "🧠 Memory: ON (Unlimited)" if user.is_vip else "🧠 Memory: ON (Max 2 Chats)"
    else:
        memory_text = "🧹 Memory: Auto-Clear (2h)"
        
    keyboard = [
        [InlineKeyboardButton(text="💎 Purchase VIP", callback_data="upgrade_vip")],
        [InlineKeyboardButton(text=toggle_text, callback_data="toggle_model")],
        [InlineKeyboardButton(text=memory_text, callback_data="toggle_memory")],
        [InlineKeyboardButton(text="🎁 Redeem Code", callback_data="redeem_promo_code")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_cancel_promo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_promo_action")]
    ])

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

def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """The main entry point for the Admin Dashboard."""
    keyboard = [
        [InlineKeyboardButton(text="📊 Live Statistics", callback_data="adm_main_stats")],
        [InlineKeyboardButton(text="👥 Manage Users", callback_data="adm_page_1")],
        [InlineKeyboardButton(text="📢 Broadcast Message", callback_data="adm_main_broadcast")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="adm_main_menu")]
    ])

def get_users_list_keyboard(users: list, current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Builds a paginated inline keyboard of users with a back button."""
    builder = InlineKeyboardBuilder()
    
    for u in users:
        status = "👑" if u.is_vip else ("🚫" if u.is_banned else "👤")
        name = u.first_name if u.first_name else "User"
        text = f"{status} {name} ({u.telegram_id})"
        builder.row(InlineKeyboardButton(text=text, callback_data=f"adm_u_{u.telegram_id}"))
        
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"adm_page_{current_page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="ignore"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"adm_page_{current_page + 1}"))
        
    if nav_row:
        builder.row(*nav_row)
        
    # Add back to main admin menu button
    builder.row(InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="adm_main_menu"))
    return builder.as_markup()

def get_admin_user_keyboard(user_id: int, is_vip: bool, is_banned: bool, current_page: int = 1) -> InlineKeyboardMarkup:
    """Updated user detail keyboard with a Back to List button."""
    vip_text = "❌ Remove VIP" if is_vip else "👑 Make VIP"
    ban_text = "✅ Unban User" if is_banned else "🚫 Ban User"
    
    keyboard = [
        [InlineKeyboardButton(text="➕ Add 50 Premium Credits", callback_data=f"adm_cred_{user_id}_{current_page}")],
        [
            InlineKeyboardButton(text=vip_text, callback_data=f"adm_vip_{user_id}_{current_page}"),
            InlineKeyboardButton(text=ban_text, callback_data=f"adm_ban_{user_id}_{current_page}")
        ],
        [InlineKeyboardButton(text="🔙 Back to Users List", callback_data=f"adm_page_{current_page}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
