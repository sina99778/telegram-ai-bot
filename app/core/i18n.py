TEXTS = {
    "en": {
        "btn_chat": "💬 AI Chat",
        "btn_image": "🖼 Image Lab",
        "btn_vip": "✨ VIP & Pro",
        "btn_profile": "👛 Wallet & Profile",
        "btn_invite": "🎁 Invite & Earn",
        "btn_support": "🆘 Support",
        "btn_admin": "🛠 Admin Panel",
        "btn_lang": "🌐 Language: EN",
        "lang_changed": "🇬🇧 Language changed to English!",
        "menu_hint": "Choose an option",
        "welcome": "👋 Welcome to the <b>AI Hub</b>!\n\nChoose an option below:",
    },
    "fa": {
        "btn_chat": "💬 چت هوش مصنوعی",
        "btn_image": "🖼 آزمایشگاه تصویر",
        "btn_vip": "✨ VIP و پرو",
        "btn_profile": "👛 کیف پول و پروفایل",
        "btn_invite": "🎁 دعوت و جایزه",
        "btn_support": "🆘 پشتیبانی",
        "btn_admin": "🛠 پنل مدیریت",
        "btn_lang": "🌐 زبان: فارسی",
        "lang_changed": "🇮🇷 زبان به فارسی تغییر یافت!",
        "menu_hint": "یک گزینه را انتخاب کنید",
        "welcome": "👋 به <b>هاب هوش مصنوعی</b> خوش آمدید!\n\nیک گزینه را انتخاب کنید:",
    },
}


def t(key: str, lang: str = "fa") -> str:
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)
