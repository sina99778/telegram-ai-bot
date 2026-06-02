from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from app.core.config import settings
from app.core.i18n import t


def get_main_menu(lang: str, *, is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = []
    # Mini App opener (only when a public HTTPS url is configured/derivable).
    webapp_url = settings.webapp_url
    if webapp_url.startswith("https://"):
        keyboard.append([KeyboardButton(text=t(lang, "buttons.open_app"), web_app=WebAppInfo(url=webapp_url))])

    keyboard += [
        [KeyboardButton(text=t(lang, "buttons.chat")), KeyboardButton(text=t(lang, "buttons.search"))],
        [KeyboardButton(text=t(lang, "buttons.image")), KeyboardButton(text=t(lang, "buttons.image_edit"))],
        [KeyboardButton(text=t(lang, "buttons.wallet")), KeyboardButton(text=t(lang, "buttons.vip"))],
        [KeyboardButton(text=t(lang, "buttons.invite")), KeyboardButton(text=t(lang, "buttons.support"))],
        [KeyboardButton(text=t(lang, "buttons.guide")), KeyboardButton(text=t(lang, "buttons.language"))],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text=t(lang, "buttons.admin"))])
    from app.bot.keyboards.styling import colorize_reply_markup

    return colorize_reply_markup(
        ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            input_field_placeholder=t(lang, "main.menu_placeholder"),
        )
    )
