from __future__ import annotations

from aiogram.types import InlineKeyboardButton

from app.bot.keyboards.common import markup, nav_buttons
from app.core.i18n import t


def get_language_picker_keyboard() -> object:
    return markup(
        [
            [
                InlineKeyboardButton(text=t("fa", "buttons.lang_fa"), callback_data="lang:set:fa"),
                InlineKeyboardButton(text=t("en", "buttons.lang_en"), callback_data="lang:set:en"),
            ]
        ]
    )


def get_profile_keyboard(user) -> object:
    lang = user.language or "fa"
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    toggle_text = t(lang, "buttons.switch_to_pro") if current_model == "FLASH" else t(lang, "buttons.switch_to_flash")
    memory_text = t(lang, "buttons.memory_on") if user.keep_chat_history else t(lang, "buttons.memory_off")

    rows = [
        [
            InlineKeyboardButton(text=t(lang, "buttons.refresh"), callback_data="profile_refresh"),
            InlineKeyboardButton(text=t(lang, "buttons.redeem"), callback_data="redeem_promo_code"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "buttons.wallet"), callback_data="profile_refresh"),
            InlineKeyboardButton(text=t(lang, "buttons.vip"), callback_data="upgrade_vip"),
        ],
        [
            InlineKeyboardButton(text=toggle_text, callback_data="toggle_model"),
            InlineKeyboardButton(text=memory_text, callback_data="toggle_memory"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "buttons.history"), callback_data="view_chat_history"),
            InlineKeyboardButton(text=t(lang, "buttons.daily_reward"), callback_data="claim_daily_reward"),
        ],
    ]
    rows.extend(nav_buttons(lang, home="cancel_action"))
    return markup(rows)


def get_cancel_promo_keyboard(lang: str) -> object:
    return markup(nav_buttons(lang, back="profile_refresh", cancel="cancel_promo_action"))


def get_cancel_keyboard(lang: str) -> object:
    return markup(nav_buttons(lang, cancel="cancel_action"))


def get_vip_plans_keyboard(lang: str) -> object:
    rows = [
        [InlineKeyboardButton(text="💳 Starter Pack ($1.99)", callback_data="buy_plan_starter")],
        [InlineKeyboardButton(text="🔥 Popular Pack ($6.99)", callback_data="buy_plan_popular")],
        [InlineKeyboardButton(text="👑 Pro Pack ($14.99)", callback_data="buy_plan_pro")],
    ]
    rows.extend(nav_buttons(lang, back="profile_refresh", home="cancel_action"))
    return markup(rows)
