from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.core.i18n import t


def get_main_menu(lang: str = "fa", *, is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=t("btn_chat", lang)), KeyboardButton(text=t("btn_image", lang))],
        [KeyboardButton(text=t("btn_profile", lang)), KeyboardButton(text=t("btn_vip", lang))],
        [KeyboardButton(text=t("btn_invite", lang)), KeyboardButton(text=t("btn_support", lang))],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text=t("btn_admin", lang))])
    keyboard.append([KeyboardButton(text=t("btn_lang", lang))])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, input_field_placeholder=t("menu_hint", lang))
