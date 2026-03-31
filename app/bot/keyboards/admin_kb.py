from __future__ import annotations

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.common import markup, nav_buttons
from app.core.i18n import t
from app.db.models import PromoCode, User


def get_admin_main_kb(lang: str) -> object:
    return markup(
        [
            [
                InlineKeyboardButton(text=t(lang, "buttons.admin_stats"), callback_data="admin:stats"),
                InlineKeyboardButton(text=t(lang, "buttons.admin_users"), callback_data="admin:users:page:1"),
            ],
            [
                InlineKeyboardButton(text="💳 Wallet & VIP", callback_data="admin:users:page:1"),
                InlineKeyboardButton(text=t(lang, "buttons.admin_codes"), callback_data="admin:codes"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.admin_broadcast"), callback_data="admin:broadcast"),
                InlineKeyboardButton(text=t(lang, "buttons.admin_pricing"), callback_data="admin:pricing"),
            ],
            [InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main")],
        ]
    )


def get_back_to_admin_kb(lang: str, back: str | None = None) -> object:
    return markup(nav_buttons(lang, back=back, home="admin:main", refresh="admin:main"))


def get_admin_users_kb(users: list[User], page: int, total_pages: int, search: str | None, lang: str) -> object:
    builder = InlineKeyboardBuilder()
    search_token = search or "-"

    for user in users:
        display_name = user.username or user.first_name or "unknown"
        vip_status = t(lang, "admin.user_vip_short") if user.has_active_vip else t(lang, "admin.user_free_short")
        ban_status = "🚫" if user.is_banned else "✅"
        label = f"{ban_status} {display_name} | N:{user.normal_credits} V:{user.vip_credits} | {vip_status}"
        builder.row(
            InlineKeyboardButton(
                text=label[:64],
                callback_data=f"admin:user:{user.telegram_id}:page:{page}:search:{search_token}",
            )
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin:users:page:{page - 1}:search:{search_token}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="admin:noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"admin:users:page:{page + 1}:search:{search_token}"))
    builder.row(*nav_row)
    builder.row(
        InlineKeyboardButton(text=t(lang, "admin.search"), callback_data="admin:users:search"),
        InlineKeyboardButton(text=t(lang, "buttons.refresh"), callback_data=f"admin:users:page:{page}:search:{search_token}"),
    )
    builder.row(InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"))
    return builder.as_markup()


def get_user_manage_kb(user: User, lang: str, page: int = 1, search: str | None = None) -> object:
    search_token = search or "-"
    ban_label = t(lang, "admin.unban") if user.is_banned else t(lang, "admin.ban")
    vip_label = t(lang, "admin.extend_vip") if user.has_active_vip else t(lang, "admin.give_vip")
    add_normal_cb = f"admin:user:add_normal:{user.telegram_id}:page:{page}:search:{search_token}"
    add_vip_cb = f"admin:user:add_vip:{user.telegram_id}:page:{page}:search:{search_token}"
    vip_cb = f"admin:user:vip:{user.telegram_id}:page:{page}:search:{search_token}"
    ban_cb = f"admin:user:ban:{user.telegram_id}:page:{page}:search:{search_token}"
    return markup(
        [
            [
                InlineKeyboardButton(text=t(lang, "admin.add_normal_credits"), callback_data=add_normal_cb),
                InlineKeyboardButton(text=t(lang, "admin.add_vip_credits"), callback_data=add_vip_cb),
            ],
            [
                InlineKeyboardButton(text=vip_label, callback_data=vip_cb),
                InlineKeyboardButton(text=ban_label, callback_data=ban_cb),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data=f"admin:users:page:{page}:search:{search_token}"),
                InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
            ],
        ]
    )


def get_code_menu_kb(lang: str) -> object:
    return markup(
        [
            [
                InlineKeyboardButton(text="➕ Create Code", callback_data="admin:codes:create"),
                InlineKeyboardButton(text="📋 Active Codes", callback_data="admin:codes:list"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.refresh"), callback_data="admin:codes"),
                InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
            ],
        ]
    )


def get_code_kind_kb(lang: str) -> object:
    return markup(
        [
            [InlineKeyboardButton(text="🎁 Gift Normal Credits", callback_data="admin:codes:kind:gift_normal_credits")],
            [InlineKeyboardButton(text="💎 Gift VIP Credits", callback_data="admin:codes:kind:gift_vip_credits")],
            [InlineKeyboardButton(text="🗓 Gift VIP Days", callback_data="admin:codes:kind:gift_vip_days")],
            [InlineKeyboardButton(text="🏷 Discount Code", callback_data="admin:codes:kind:discount_percent")],
            *nav_buttons(lang, back="admin:codes", home="admin:main"),
        ]
    )


def get_code_generation_kb(lang: str) -> object:
    return markup(
        [
            [InlineKeyboardButton(text="⚡ Auto Generate", callback_data="admin:codes:generate:auto")],
            [InlineKeyboardButton(text="⌨️ Manual Input", callback_data="admin:codes:generate:manual")],
            *nav_buttons(lang, back="admin:codes", cancel="admin:main"),
        ]
    )


def get_codes_list_kb(codes: list[PromoCode], lang: str) -> object:
    builder = InlineKeyboardBuilder()
    for code in codes:
        builder.row(
            InlineKeyboardButton(
                text=f"🎟 {code.code} | {code.kind.value} | {code.used_count}/{code.max_uses}",
                callback_data=f"admin:codes:view:{code.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data="admin:codes"),
        InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
    )
    return builder.as_markup()


def get_code_detail_kb(code_id: int, lang: str) -> object:
    return markup(
        [
            [
                InlineKeyboardButton(text="🚫 Disable", callback_data=f"admin:codes:disable:{code_id}"),
                InlineKeyboardButton(text="📈 Usage", callback_data=f"admin:codes:usage:{code_id}"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data="admin:codes:list"),
                InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
            ],
        ]
    )
