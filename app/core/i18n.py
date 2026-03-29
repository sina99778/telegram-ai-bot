TEXTS = {
    "en": {
        "btn_chat": "💬 Chat with AI", "btn_image": "🖼️ Generate Image",
        "btn_voice": "🎙️ Voice Assistant", "btn_vip": "👑 VIP Premium",
        "btn_profile": "👤 My Profile", "btn_invite": "🎁 Invite Friends",
        "btn_support": "📞 Support", "btn_lang": "🌐 Language: EN",
        "lang_changed": "🇬🇧 Language changed to English!",
        "welcome": "👋 Welcome to the <b>AI Hub</b>!\n\nChoose an option below:"
    },
    "fa": {
        "btn_chat": "💬 چت با هوش مصنوعی", "btn_image": "🖼️ ساخت تصویر",
        "btn_voice": "🎙️ دستیار صوتی", "btn_vip": "👑 اشتراک ویژه",
        "btn_profile": "👤 پروفایل من", "btn_invite": "🎁 دعوت از دوستان",
        "btn_support": "📞 پشتیبانی", "btn_lang": "🌐 زبان: فارسی",
        "lang_changed": "🇮🇷 زبان به فارسی تغییر یافت!",
        "welcome": "👋 به <b>هاب هوش مصنوعی</b> خوش آمدید!\n\nیک گزینه را انتخاب کنید:"
    }
}

def t(key: str, lang: str = "fa") -> str:
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)
