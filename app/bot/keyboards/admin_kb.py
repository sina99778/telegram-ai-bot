from __future__ import annotations

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.common import markup, nav_buttons
from app.core.i18n import t
from app.db.models import PromoCode, User

# Telegram caps callback_data at 64 BYTES. The admin user-list embeds the
# current search term inside several callbacks (pagination + per-user actions).
# A long term — or a short Persian one (2 bytes/char in UTF-8) — would push the
# data past 64 bytes and Telegram would reject the WHOLE message, not just the
# button. We therefore round-trip only a short, byte-bounded, colon-free token;
# the first search still queries the full term, only deep-link navigation uses
# the shortened token.
_SEARCH_TOKEN_BUDGET = 12


def _safe_search_token(search: str | None) -> str:
    token = (search or "").strip()
    if not token:
        return "-"
    # ':' is the callback_data delimiter — neutralise it so parsing stays sane.
    token = token.replace(":", " ")
    encoded = token.encode("utf-8")
    if len(encoded) <= _SEARCH_TOKEN_BUDGET:
        return token
    return encoded[:_SEARCH_TOKEN_BUDGET].decode("utf-8", "ignore").strip() or "-"


def get_admin_main_kb(lang: str) -> object:
    return markup(
        [
            [
                InlineKeyboardButton(text=t(lang, "buttons.admin_stats"), callback_data="admin:stats"),
                InlineKeyboardButton(text=t(lang, "buttons.admin_users"), callback_data="admin:users:page:1"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.admin_abuse"), callback_data="admin:abuse"),
                InlineKeyboardButton(text=t(lang, "buttons.admin_codes"), callback_data="admin:codes"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.admin_broadcast"), callback_data="admin:broadcast"),
                InlineKeyboardButton(text=t(lang, "buttons.admin_pricing"), callback_data="admin:pricing"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.admin_config"), callback_data="admin:config"),
                InlineKeyboardButton(text=t(lang, "buttons.admin_cardpay"), callback_data="admin:cardpay:list"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
            ],
        ]
    )


# Runtime-config keys grouped into tappable sections (better than one long list).
# Keys not listed here still work via /setconfig; they just won't show a button.
CONFIG_SECTIONS: dict[str, list[str]] = {
    "pricing": [
        "normal_message_cost", "vip_message_cost",
        "image_credit_cost", "image_edit_credit_cost",
        "payg_flash_per_1k", "payg_pro_per_1k", "payg_min_charge",
    ],
    "limits": [
        "search_daily_free", "search_daily_paid", "search_daily_vip", "search_daily_group",
        "free_daily_image", "free_weekly_image_edit", "inline_daily", "daily_free_credits",
    ],
    "context": [
        "history_max_tokens", "history_max_messages",
        "max_output_tokens_flash", "max_output_tokens_pro",
    ],
    "payments": ["usd_toman_rate"],
}
# Free-text settings shown inside the Payments section.
PAYMENTS_TEXT_KEYS = ["card_number", "card_holder", "card_note"]


def section_for_key(key: str) -> str | None:
    for section, keys in CONFIG_SECTIONS.items():
        if key in keys:
            return section
    if key in PAYMENTS_TEXT_KEYS:
        return "payments"
    return None


def get_admin_config_kb(lang: str) -> object:
    """Top-level settings screen: one button per section (not one giant list)."""
    return markup(
        [
            [
                InlineKeyboardButton(text=t(lang, "admin.config.cat.pricing"), callback_data="admin:config:cat:pricing"),
                InlineKeyboardButton(text=t(lang, "admin.config.cat.limits"), callback_data="admin:config:cat:limits"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "admin.config.cat.context"), callback_data="admin:config:cat:context"),
                InlineKeyboardButton(text=t(lang, "admin.config.cat.payments"), callback_data="admin:config:cat:payments"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "admin.config.cat.emoji"), callback_data="admin:emoji"),
                InlineKeyboardButton(text=t(lang, "admin.config.cat.join"), callback_data="admin:join"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "buttons.refresh"), callback_data="admin:config"),
                InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
            ],
        ]
    )


def get_admin_join_kb(lang: str, *, enabled: bool, has_channel: bool) -> object:
    """Forced-join manager: toggle + set/clear channel."""
    rows = [
        [
            InlineKeyboardButton(
                text=t(lang, "admin.join.toggle_off" if enabled else "admin.join.toggle_on"),
                callback_data="admin:join:toggle",
            )
        ],
        [
            InlineKeyboardButton(text=t(lang, "admin.join.set_channel_btn"), callback_data="admin:join:setchannel"),
        ],
    ]
    if has_channel:
        rows.append([InlineKeyboardButton(text=t(lang, "admin.join.clear_btn"), callback_data="admin:join:clear")])
    rows.append(
        [
            InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data="admin:config"),
            InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
        ]
    )
    return markup(rows)


def get_admin_config_section_kb(
    section: str,
    snapshot: list[dict],
    lang: str,
    text_items: list[dict] | None = None,
) -> object:
    """The settings inside one section: a button per numeric/text key, plus
    (for payments) the live-rate fetch button."""
    order = CONFIG_SECTIONS.get(section, [])
    by_key = {item["key"]: item for item in snapshot}
    builder = InlineKeyboardBuilder()
    for key in order:
        item = by_key.get(key)
        if not item:
            continue
        star = " ★" if item["is_override"] else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{item['key']} = {item['value']}{star}"[:64],
                callback_data=f"admin:config:set:{item['key']}",
            )
        )
    for item in (text_items or []):
        shown = item.get("value") or "—"
        builder.row(
            InlineKeyboardButton(
                text=f"{item['key']}: {shown}"[:64],
                callback_data=f"admin:config:settext:{item['key']}",
            )
        )
    if section == "payments":
        builder.row(
            InlineKeyboardButton(text=t(lang, "admin.config.fetch_rate_btn"), callback_data="admin:config:fetchrate"),
        )
    builder.row(
        InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data="admin:config"),
        InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
    )
    return builder.as_markup()


def get_admin_emoji_kb(lang: str, *, enabled: bool, configured_slugs: set[str]) -> object:
    """Premium-emoji manager: a toggle + the complete list of UI emojis as
    buttons (✅ mapped / ➕ unset). Status mark is placed FIRST so the styler
    never premiumizes the emoji shown here (the admin must see the plain emoji)."""
    from app.services.config.premium_emoji_store import EMOJI_REGISTRY

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t(lang, "admin.emoji.toggle_off" if enabled else "admin.emoji.toggle_on"),
            callback_data="admin:emoji:toggle",
        )
    )
    row: list[InlineKeyboardButton] = []
    for slug, emoji, _label in EMOJI_REGISTRY:
        mark = "✅" if slug in configured_slugs else "➕"
        row.append(InlineKeyboardButton(text=f"{mark} {emoji}", callback_data=f"admin:emoji:s:{slug}"))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(
        InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data="admin:config"),
        InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
    )
    return builder.as_markup()


def get_back_to_admin_kb(lang: str, back: str | None = None) -> object:
    return markup(nav_buttons(lang, back=back, home="admin:main", refresh="admin:main"))


def get_admin_users_kb(users: list[User], page: int, total_pages: int, search: str | None, lang: str) -> object:
    builder = InlineKeyboardBuilder()
    search_token = _safe_search_token(search)

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
    search_token = _safe_search_token(search)
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


def get_broadcast_control_kb(lang: str) -> object:
    return markup(
        [
            [InlineKeyboardButton(text=t(lang, "buttons.stop_broadcast"), callback_data="admin:broadcast:stop")],
            [InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main")],
        ]
    )
