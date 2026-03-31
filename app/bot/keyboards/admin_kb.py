from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import PromoCode, User


def get_admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Statistics", callback_data="admin:stats"),
                InlineKeyboardButton(text="👥 Users", callback_data="admin:users:page:1"),
            ],
            [
                InlineKeyboardButton(text="💳 Wallet & VIP", callback_data="admin:users:page:1"),
                InlineKeyboardButton(text="🎟 Codes", callback_data="admin:codes"),
            ],
            [
                InlineKeyboardButton(text="📣 Broadcast", callback_data="admin:broadcast"),
                InlineKeyboardButton(text="⚙️ Pricing", callback_data="admin:pricing"),
            ],
            [InlineKeyboardButton(text="🏠 Home", callback_data="admin:main")],
        ]
    )


def get_back_to_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:main"),
                InlineKeyboardButton(text="🏠 Admin Home", callback_data="admin:main"),
            ]
        ]
    )


def get_admin_users_kb(users: list[User], page: int, total_pages: int, search: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    search_token = search or "-"

    for user in users:
        display_name = user.username or user.first_name or "unknown"
        vip_status = "VIP" if user.has_active_vip else "Free"
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
        nav_row.append(
            InlineKeyboardButton(text="⬅️ Prev", callback_data=f"admin:users:page:{page - 1}:search:{search_token}")
        )
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="admin:noop"))
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(text="Next ➡️", callback_data=f"admin:users:page:{page + 1}:search:{search_token}")
        )
    builder.row(*nav_row)
    builder.row(
        InlineKeyboardButton(text="🔎 Search", callback_data="admin:users:search"),
        InlineKeyboardButton(text="🔄 Refresh", callback_data=f"admin:users:page:{page}:search:{search_token}"),
    )
    builder.row(InlineKeyboardButton(text="🏠 Admin Home", callback_data="admin:main"))
    return builder.as_markup()


def get_user_manage_kb(user: User, page: int = 1, search: str | None = None) -> InlineKeyboardMarkup:
    search_token = search or "-"
    ban_label = "✅ Unban" if user.is_banned else "🚫 Ban"
    vip_label = "🗓 Extend VIP" if user.has_active_vip else "✨ Give VIP"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Normal Credits", callback_data=f"admin:user:add_normal:{user.telegram_id}"),
                InlineKeyboardButton(text="➕ VIP Credits", callback_data=f"admin:user:add_vip:{user.telegram_id}"),
            ],
            [
                InlineKeyboardButton(text=vip_label, callback_data=f"admin:user:vip:{user.telegram_id}"),
                InlineKeyboardButton(text=ban_label, callback_data=f"admin:user:ban:{user.telegram_id}"),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Back to Users",
                    callback_data=f"admin:users:page:{page}:search:{search_token}",
                ),
                InlineKeyboardButton(text="🏠 Admin Home", callback_data="admin:main"),
            ],
        ]
    )


def get_code_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Create Code", callback_data="admin:codes:create"),
                InlineKeyboardButton(text="📋 Active Codes", callback_data="admin:codes:list"),
            ],
            [
                InlineKeyboardButton(text="🔄 Refresh", callback_data="admin:codes"),
                InlineKeyboardButton(text="🏠 Admin Home", callback_data="admin:main"),
            ],
        ]
    )


def get_code_kind_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Gift Normal Credits", callback_data="admin:codes:kind:gift_normal_credits")],
            [InlineKeyboardButton(text="💎 Gift VIP Credits", callback_data="admin:codes:kind:gift_vip_credits")],
            [InlineKeyboardButton(text="🗓 Gift VIP Days", callback_data="admin:codes:kind:gift_vip_days")],
            [InlineKeyboardButton(text="🏷 Discount Code", callback_data="admin:codes:kind:discount_percent")],
            [
                InlineKeyboardButton(text="⬅️ Back", callback_data="admin:codes"),
                InlineKeyboardButton(text="🏠 Admin Home", callback_data="admin:main"),
            ],
        ]
    )


def get_code_generation_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Auto Generate", callback_data="admin:codes:generate:auto")],
            [InlineKeyboardButton(text="⌨️ Manual Input", callback_data="admin:codes:generate:manual")],
            [
                InlineKeyboardButton(text="⬅️ Back", callback_data="admin:codes"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="admin:main"),
            ],
        ]
    )


def get_codes_list_kb(codes: list[PromoCode]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code in codes:
        builder.row(
            InlineKeyboardButton(
                text=f"🎟 {code.code} | {code.kind.value} | {code.used_count}/{code.max_uses}",
                callback_data=f"admin:codes:view:{code.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Back", callback_data="admin:codes"),
        InlineKeyboardButton(text="🏠 Admin Home", callback_data="admin:main"),
    )
    return builder.as_markup()


def get_code_detail_kb(code_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚫 Disable", callback_data=f"admin:codes:disable:{code_id}"),
                InlineKeyboardButton(text="📈 Usage", callback_data=f"admin:codes:usage:{code_id}"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Back", callback_data="admin:codes:list"),
                InlineKeyboardButton(text="🏠 Admin Home", callback_data="admin:main"),
            ],
        ]
    )
