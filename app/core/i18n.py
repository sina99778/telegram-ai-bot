TEXTS = {
    "en": {
        "btn_chat": "💬 Chat with AI",
        "btn_image": "🖼️ Generate Image",
        "btn_voice": "🎙️ Voice Assistant",
        "btn_profile": "👤 My Profile",
        "btn_invite": "🎁 Invite Friends",
        "btn_lang": "🌐 Language: EN",
        "lang_changed": "🇬🇧 Language successfully changed to English!",
        "welcome": "👋 Welcome to the AI Hub!\n\nChoose an option from the menu to get started."
    },
    "fa": {
        "btn_chat": "💬 چت با هوش مصنوعی",
        "btn_image": "🖼️ ساخت تصویر",
        "btn_voice": "🎙️ دستیار صوتی",
        "btn_profile": "👤 پروفایل من",
        "btn_invite": "🎁 دعوت از دوستان",
        "btn_lang": "🌐 زبان: فارسی",
        "lang_changed": "🇮🇷 زبان ربات با موفقیت به فارسی تغییر یافت!",
        "welcome": "👋 به هاب هوش مصنوعی خوش آمدید!\n\nبرای شروع یکی از گزینههای زیر را انتخاب کنید."
    }
}

def t(key: str, lang: str = "fa") -> str:
    """Returns the translated text for the given key and language."""
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)
