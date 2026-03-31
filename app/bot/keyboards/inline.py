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
            InlineKeyboardButton(text=t(lang, "buttons.wallet"), callback_data="wallet:open"),
            InlineKeyboardButton(text=t(lang, "buttons.vip"), callback_data="vip:open"),
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


def get_wallet_menu_keyboard(lang: str) -> object:
    return markup(
        [
            [InlineKeyboardButton(text=t(lang, "buttons.buy_normal"), callback_data="wallet:buy_normal")],
            [InlineKeyboardButton(text=t(lang, "buttons.buy_vip"), callback_data="wallet:buy_vip")],
            [InlineKeyboardButton(text=t(lang, "buttons.buy_vip_access"), callback_data="wallet:buy_access")],
            [InlineKeyboardButton(text=t(lang, "buttons.redeem"), callback_data="redeem_promo_code")],
            [InlineKeyboardButton(text=t(lang, "buttons.my_balance"), callback_data="profile_refresh")],
            *nav_buttons(lang, back="profile_refresh", home="cancel_action"),
        ]
    )


def get_vip_menu_keyboard(lang: str) -> object:
    return markup(
        [
            [InlineKeyboardButton(text=t(lang, "buttons.vip_benefits"), callback_data="vip:benefits")],
            [InlineKeyboardButton(text=t(lang, "buttons.buy_vip_access"), callback_data="wallet:buy_access")],
            [InlineKeyboardButton(text=t(lang, "buttons.buy_vip"), callback_data="wallet:buy_vip")],
            *nav_buttons(lang, back="profile_refresh", home="cancel_action"),
        ]
    )


def get_support_menu_keyboard(lang: str) -> object:
    return markup(
        [
            [InlineKeyboardButton(text=t(lang, "buttons.contact_support"), url="https://t.me/ThereIsStillSina")],
            [InlineKeyboardButton(text=t(lang, "buttons.report_problem"), url="https://t.me/ThereIsStillSina")],
            *nav_buttons(lang, back="support:back", home="cancel_action"),
        ]
    )


def get_normal_credit_packs_keyboard(lang: str) -> object:
    rows = [
        [InlineKeyboardButton(text=t(lang, "packs.normal_100"), callback_data="purchase:normal_100")],
        [InlineKeyboardButton(text=t(lang, "packs.normal_350"), callback_data="purchase:normal_350")],
        [InlineKeyboardButton(text=t(lang, "packs.normal_800"), callback_data="purchase:normal_800")],
    ]
    rows.extend(nav_buttons(lang, back="wallet:open", home="cancel_action"))
    return markup(rows)


def get_vip_credit_packs_keyboard(lang: str) -> object:
    rows = [
        [InlineKeyboardButton(text=t(lang, "packs.vip_150"), callback_data="purchase:vip_150")],
        [InlineKeyboardButton(text=t(lang, "packs.vip_700"), callback_data="purchase:vip_700")],
        [InlineKeyboardButton(text=t(lang, "packs.vip_1800"), callback_data="purchase:vip_1800")],
    ]
    rows.extend(nav_buttons(lang, back="wallet:open", home="cancel_action"))
    return markup(rows)


def get_vip_access_packs_keyboard(lang: str) -> object:
    rows = [
        [InlineKeyboardButton(text=t(lang, "packs.access_30d"), callback_data="purchase:access_30d")],
        [InlineKeyboardButton(text=t(lang, "packs.access_90d"), callback_data="purchase:access_90d")],
    ]
    rows.extend(nav_buttons(lang, back="wallet:open", home="cancel_action"))
    return markup(rows)


def get_checkout_keyboard(lang: str, url: str) -> object:
    rows = [
        [InlineKeyboardButton(text=t(lang, "buttons.checkout"), url=url)],
    ]
    rows.extend(nav_buttons(lang, back="wallet:open", home="cancel_action"))
    return markup(rows)


def get_cancel_promo_keyboard(lang: str) -> object:
    return markup(nav_buttons(lang, back="wallet:open", cancel="cancel_promo_action"))


def get_cancel_keyboard(lang: str) -> object:
    return markup(nav_buttons(lang, cancel="cancel_action"))
