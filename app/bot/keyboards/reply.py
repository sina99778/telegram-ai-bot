from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from app.core.i18n import t

def get_main_menu(lang: str = "fa") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_chat", lang)), KeyboardButton(text=t("btn_image", lang))],
            [KeyboardButton(text=t("btn_profile", lang)), KeyboardButton(text=t("btn_vip", lang))],
            [KeyboardButton(text=t("btn_invite", lang)), KeyboardButton(text=t("btn_support", lang))],
            [KeyboardButton(text=t("btn_lang", lang))]
        ],
        resize_keyboard=True
    )
