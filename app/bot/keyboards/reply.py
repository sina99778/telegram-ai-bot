from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_menu() -> ReplyKeyboardMarkup:
    """Returns the main bottom keyboard menu."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 Chat with AI"), KeyboardButton(text="🖼️ Generate Image")],
            [KeyboardButton(text="🎙️ Voice Assistant"), KeyboardButton(text="👑 VIP Premium")],
            [KeyboardButton(text="👤 My Profile"), KeyboardButton(text="🎁 Invite Friends")],
            [KeyboardButton(text="📞 Support")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Select an option or type a message..."
    )
