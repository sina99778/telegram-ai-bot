from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.core.i18n import t


def get_main_menu(lang: str, *, is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=t(lang, "buttons.chat")), KeyboardButton(text=t(lang, "buttons.image"))],
        [KeyboardButton(text=t(lang, "buttons.wallet")), KeyboardButton(text=t(lang, "buttons.vip"))],
        [KeyboardButton(text=t(lang, "buttons.invite")), KeyboardButton(text=t(lang, "buttons.support"))],
        [KeyboardButton(text=t(lang, "buttons.language"))],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text=t(lang, "buttons.admin"))])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder=t(lang, "main.menu_placeholder"),
    )
