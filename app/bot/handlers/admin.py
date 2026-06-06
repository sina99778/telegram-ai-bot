from __future__ import annotations

import asyncio
import html
import logging
import secrets
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_kb import (
    _safe_search_token,
    PAYMENTS_TEXT_KEYS,
    get_admin_config_kb,
    get_admin_config_section_kb,
    get_admin_emoji_kb,
    get_admin_join_kb,
    get_admin_main_kb,
    get_admin_users_kb,
    get_back_to_admin_kb,
    get_broadcast_control_kb,
    get_code_detail_kb,
    get_code_generation_kb,
    get_code_kind_kb,
    get_code_menu_kb,
    get_codes_list_kb,
    get_user_manage_kb,
    section_for_key,
)
from app.core.access import is_configured_admin
from app.core.config import settings
from app.core.enums import PromoCodeKind, TransactionStatus, WalletType
from app.core.i18n import t
from app.db.models import FeatureConfig, PaymentTransaction, User
from app.services.admin.admin_service import AdminService
from app.services.billing.billing_service import BillingService
from app.services.config.runtime_config import RuntimeConfig
from app.services.purchase.catalog import get_product
from app.services.purchase.fulfillment import apply_product
from app.services.security.abuse_guard import AbuseGuardService
from app.services.security.broadcast_control import BroadcastControlService

admin_router = Router(name="admin")
logger = logging.getLogger(__name__)


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_user_search = State()
    waiting_for_credit_amount = State()
    waiting_for_vip_days = State()
    waiting_for_code_amount = State()
    waiting_for_code_expiry_days = State()
    waiting_for_code_max_uses = State()
    waiting_for_code_max_uses_per_user = State()
    waiting_for_manual_code = State()
    waiting_for_config_value = State()
    waiting_for_config_text = State()
    waiting_for_premium_emoji = State()
    waiting_for_join_channel = State()


async def _is_admin(user_id: int, session: AsyncSession) -> bool:
    return is_configured_admin(user_id)


def _admin_service(session: AsyncSession) -> AdminService:
    return AdminService(session, BillingService(session))


def _format_user_detail(user: User) -> str:
    lang = _lang(user)
    display_name = html.escape(user.username or user.first_name or "unknown")
    vip_until = user.active_vip_until
    vip_status = t(lang, "admin.user_vip_until", date=vip_until.strftime("%Y-%m-%d")) if user.has_active_vip and vip_until else (
        t(lang, "admin.user_vip_active") if user.has_active_vip else t(lang, "admin.user_vip_inactive")
    )
    ban_status = t(lang, "admin.user_banned") if user.is_banned else t(lang, "admin.user_not_banned")
    return (
        f"<b>{t(lang, 'admin.user_management_title')}</b>\n\n"
        f"{t(lang, 'admin.user_id')}: <code>{user.telegram_id}</code>\n"
        f"{t(lang, 'admin.user_name')}: {display_name}\n"
        f"{t(lang, 'admin.user_normal_credits')}: <code>{user.normal_credits}</code>\n"
        f"{t(lang, 'admin.user_vip_credits')}: <code>{user.vip_credits}</code>\n"
        f"{t(lang, 'admin.user_vip_status')}: <b>{vip_status}</b>\n"
        f"{t(lang, 'admin.user_ban_status')}: <b>{ban_status}</b>"
    )


def _admin_action_error(lang: str) -> str:
    return t(lang, "admin.action_failed")


def _admin_saved(lang: str) -> str:
    return t(lang, "admin.action_saved")


async def _guard_admin_mutation(*, admin_id: int, lang: str, action: str, callback: CallbackQuery | None = None, message: Message | None = None) -> bool:
    decision = await AbuseGuardService.check_admin_action(admin_id=admin_id, action=action, lang=lang)
    if decision.allowed:
        return True
    if callback:
        await callback.answer(decision.reason, show_alert=True)
    elif message:
        await message.answer(decision.reason)
    return False


def _parse_page_search(parts: list[str]) -> tuple[int, str | None]:
    try:
        p_idx = parts.index("page")
        page = int(parts[p_idx + 1])
    except (ValueError, IndexError):
        page = 1
        
    try:
        s_idx = parts.index("search")
        search = parts[s_idx + 1]
        if search == "-":
            search = None
    except (ValueError, IndexError):
        search = None
        
    return page, search


def _user_detail_callback(telegram_id: int, page: int, search: str | None) -> str:
    return f"admin:user:{telegram_id}:page:{page}:search:{_safe_search_token(search)}"


def _format_stats(stats: dict) -> str:
    return (
        "<b>System Statistics</b>\n\n"
        f"Users: <code>{stats['total_users']}</code>\n"
        f"Active users: <code>{stats['total_active_users']}</code>\n"
        f"VIP users: <code>{stats['total_vip_users']}</code>\n"
        f"Banned users: <code>{stats['total_banned_users']}</code>\n"
        f"Normal credits in circulation: <code>{stats['total_normal_credits']}</code>\n"
        f"VIP credits in circulation: <code>{stats['total_vip_credits']}</code>\n"
        f"Completed payments: <code>{stats['total_payments_completed']}</code>\n"
        f"Failed payments: <code>{stats['total_payments_failed']}</code>"
    )


def _format_abuse_overview(lang: str, overview: dict) -> str:
    lines = [t(lang, "admin.abuse_title"), ""]

    lines.append(t(lang, "admin.abuse_active_anomalies"))
    if overview["active_anomalies"]:
        for item in overview["active_anomalies"][:5]:
            lines.append(
                f"- {item['scope_type']} <code>{item['scope_id']}</code> / {item['feature']} · <code>{item['count']}</code> · {item['ttl']}s"
            )
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_top_users"))
    if overview["top_users"]:
        for item in overview["top_users"]:
            lines.append(f"- <code>{item['telegram_id']}</code> {item['name']} · <code>{item['count']}</code>")
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_top_groups"))
    if overview["top_groups"]:
        for item in overview["top_groups"]:
            lines.append(f"- <code>{item['group_id']}</code> · <code>{item['count']}</code>")
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_top_images"))
    if overview["top_images"]:
        for item in overview["top_images"]:
            lines.append(f"- <code>{item['telegram_id']}</code> {item['name']} · <code>{item['count']}</code>")
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_temp_blocks"))
    if overview["temp_blocks"]:
        for item in overview["temp_blocks"]:
            lines.append(f"- {item['subject']} <code>{item['subject_id']}</code> · {item['ttl']}s")
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_contained_users"))
    if overview["contained_users"]:
        for item in overview["contained_users"][:5]:
            lines.append(f"- <code>{item['scope_id']}</code> / {item['feature']} · {item['ttl']}s")
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_contained_groups"))
    if overview["contained_groups"]:
        for item in overview["contained_groups"][:5]:
            lines.append(f"- <code>{item['scope_id']}</code> / {item['feature']} · {item['ttl']}s")
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_feature_counts"))
    if overview["feature_anomaly_counts"]:
        for feature, count in sorted(overview["feature_anomaly_counts"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- {feature}: <code>{count}</code>")
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_recent_spikes"))
    if overview["recent_spikes"]:
        for item in overview["recent_spikes"][:5]:
            lines.append(f"- {item['scope_type']} <code>{item['scope_id']}</code> / {item['feature']} · <code>{item['count']}</code>")
    else:
        lines.append("- <code>none</code>")
    lines.append("")

    lines.append(t(lang, "admin.abuse_failures"))
    if overview["recent_failures"]:
        for item in overview["recent_failures"]:
            lines.append(f"- {item['subject']} <code>{item['subject_id']}</code> · <code>{item['count']}</code>")
    else:
        lines.append("- <code>none</code>")
    return "\n".join(lines)


async def _render_user_page(
    message: Message | CallbackQuery,
    service: AdminService,
    page: int,
    search: str | None = None,
    lang: str = "fa",
) -> None:
    result = await service.list_users(page=page, search=search)
    text = t(lang, "admin.users_title")
    markup = get_admin_users_kb(result.users, result.page, result.total_pages, search, lang)
    target = message.message if isinstance(message, CallbackQuery) else message
    await target.edit_text(text, parse_mode="HTML", reply_markup=markup) if isinstance(message, CallbackQuery) else await target.answer(text, parse_mode="HTML", reply_markup=markup)


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession, state: FSMContext):
    if message.chat.type != "private":
        return
    if not await _is_admin(message.from_user.id, session):
        return
    await state.clear()
    await message.answer(
        t(_lang(None), "admin.panel_title"),
        parse_mode="HTML",
        reply_markup=get_admin_main_kb("fa"),
    )


@admin_router.message(Command("config"))
async def cmd_config(message: Message, session: AsyncSession):
    """List every runtime-editable limit/price with its current & default value."""
    if message.chat.type != "private":
        return
    if not await _is_admin(message.from_user.id, session):
        return
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(user)
    snapshot = await RuntimeConfig.snapshot(session)
    lines = [t(lang, "admin.config.title"), ""]
    for item in snapshot:
        lines.append(
            t(
                lang,
                "admin.config.row",
                setting=item["key"],
                value=item["value"],
                default=item["default"],
                description=item["description"],
                star=t(lang, "admin.config.override_mark") if item["is_override"] else "",
            )
        )
    # Text settings (e.g. card-to-card details)
    for key in RuntimeConfig.TEXT_REGISTRY:
        current = await RuntimeConfig.get_text(session, key)
        shown = current if current else "—"
        lines.append(f"<code>{key}</code> = {html.escape(shown)}")
    lines.append("")
    lines.append(t(lang, "admin.config.usage"))
    await message.answer("\n".join(lines), parse_mode="HTML")


@admin_router.message(Command("setconfig"))
async def cmd_setconfig(message: Message, session: AsyncSession):
    """Change a runtime-editable limit/price: /setconfig <key> <value>."""
    if message.chat.type != "private":
        return
    if not await _is_admin(message.from_user.id, session):
        return
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(user)

    if not await _guard_admin_mutation(admin_id=message.from_user.id, lang=lang, action="setconfig", message=message):
        return

    parts = (message.text or "").split(maxsplit=2)
    # parts[0] == "/setconfig"
    if len(parts) < 3:
        return await message.answer(t(lang, "admin.config.usage"), parse_mode="HTML")

    key = parts[1].strip().lower()
    raw_value = parts[2].strip()

    # Text settings (card details, etc.) — value may contain spaces.
    if RuntimeConfig.is_valid_text_key(key):
        try:
            await RuntimeConfig.set_text(session, key, raw_value, updated_by=message.from_user.id)
        except ValueError:
            return await message.answer(t(lang, "admin.config.bad_value"), parse_mode="HTML")
        logger.info("Admin text-config change admin_telegram_id=%s key=%s", message.from_user.id, key)
        return await message.answer(
            t(lang, "admin.config.saved", setting=key, value=html.escape(raw_value[:60]), old="—"),
            parse_mode="HTML",
        )

    if not RuntimeConfig.is_valid_key(key):
        return await message.answer(t(lang, "admin.config.unknown_key", setting=key), parse_mode="HTML")

    try:
        value = int(raw_value)
    except ValueError:
        return await message.answer(t(lang, "admin.config.bad_value"), parse_mode="HTML")

    old_value = await RuntimeConfig.get_int(session, key)
    try:
        await RuntimeConfig.set_int(session, key, value, updated_by=message.from_user.id)
    except ValueError:
        spec = RuntimeConfig.REGISTRY[key]
        return await message.answer(
            t(lang, "admin.config.out_of_range", setting=key, min=spec.minimum, max=spec.maximum),
            parse_mode="HTML",
        )

    logger.info(
        "Admin runtime-config change admin_telegram_id=%s key=%s old=%s new=%s",
        message.from_user.id, key, old_value, value,
    )
    await message.answer(
        t(lang, "admin.config.saved", setting=key, value=value, old=old_value),
        parse_mode="HTML",
    )


@admin_router.callback_query(F.data == "admin:config")
async def cb_admin_config(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Render the settings home: one button per section (not one giant list)."""
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    await state.clear()
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    await callback.message.edit_text(
        t(lang, "admin.config.menu_hint"),
        parse_mode="HTML",
        reply_markup=get_admin_config_kb(lang),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:config:cat:"))
async def cb_admin_config_cat(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Render the settings inside one section."""
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    await state.clear()
    section = callback.data.split(":", 3)[3]
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    await callback.message.edit_text(
        t(lang, "admin.config.section_hint", section=t(lang, f"admin.config.cat.{section}")),
        parse_mode="HTML",
        reply_markup=await _section_keyboard(session, lang, section),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:config:set:"))
async def cb_admin_config_set_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Begin editing one key: show its detail and wait for the new value."""
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    key = callback.data.split(":", 3)[3]
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    if not RuntimeConfig.is_valid_key(key):
        return await callback.answer(t(lang, "admin.config.unknown_key", setting=key), show_alert=True)

    spec = RuntimeConfig.REGISTRY[key]
    current = await RuntimeConfig.get_int(session, key)
    await state.update_data(config_key=key)
    await state.set_state(AdminStates.waiting_for_config_value)
    await callback.message.edit_text(
        t(
            lang,
            "admin.config.set_prompt",
            setting=key,
            description=spec.description,
            value=current,
            default=RuntimeConfig.default_for(key),
            min=spec.minimum,
            max=spec.maximum,
        ),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang, back="admin:config"),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_config_value)
async def process_config_value(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    admin_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(admin_user)
    if not await _guard_admin_mutation(admin_id=message.from_user.id, lang=lang, action="setconfig", message=message):
        return

    data = await state.get_data()
    key = data.get("config_key")
    if not key or not RuntimeConfig.is_valid_key(key):
        await state.clear()
        return await message.answer(t(lang, "admin.config.unknown_key", setting=key or "?"), parse_mode="HTML")

    raw = (message.text or "").strip()
    try:
        value = int(raw)
    except ValueError:
        # Keep the state so the admin can simply re-send a correct number.
        return await message.answer(t(lang, "admin.config.bad_value"), parse_mode="HTML")

    old_value = await RuntimeConfig.get_int(session, key)
    try:
        await RuntimeConfig.set_int(session, key, value, updated_by=message.from_user.id)
    except ValueError:
        spec = RuntimeConfig.REGISTRY[key]
        return await message.answer(
            t(lang, "admin.config.out_of_range", setting=key, min=spec.minimum, max=spec.maximum),
            parse_mode="HTML",
        )

    logger.info(
        "Admin runtime-config change (button) admin_telegram_id=%s key=%s old=%s new=%s",
        message.from_user.id, key, old_value, value,
    )
    await state.clear()
    await message.answer(
        t(lang, "admin.config.saved", setting=key, value=value, old=old_value),
        parse_mode="HTML",
        reply_markup=await _section_keyboard(session, lang, section_for_key(key) or "limits"),
    )


async def _section_keyboard(session: AsyncSession, lang: str, section: str):
    """Build the keyboard for one settings section (numeric + any text items)."""
    snapshot = await RuntimeConfig.snapshot(session)
    text_items = None
    if section == "payments":
        text_items = [
            {"key": key, "value": (await RuntimeConfig.get_text(session, key))[:24]}
            for key in PAYMENTS_TEXT_KEYS
        ]
    return get_admin_config_section_kb(section, snapshot, lang, text_items=text_items)


@admin_router.callback_query(F.data.startswith("admin:config:settext:"))
async def cb_admin_config_settext_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Begin editing a free-text setting (e.g. card details) via a prompt."""
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    key = callback.data.split(":", 3)[3]
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    if not RuntimeConfig.is_valid_text_key(key):
        return await callback.answer(t(lang, "admin.config.unknown_key", setting=key), show_alert=True)

    description = RuntimeConfig.TEXT_REGISTRY[key][1]
    current = await RuntimeConfig.get_text(session, key)
    await state.update_data(config_text_key=key)
    await state.set_state(AdminStates.waiting_for_config_text)
    await callback.message.edit_text(
        t(lang, "admin.config.set_text_prompt", setting=key, description=description, value=html.escape(current or "—")),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang, back="admin:config"),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_config_text)
async def process_config_text(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    admin_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(admin_user)
    if not await _guard_admin_mutation(admin_id=message.from_user.id, lang=lang, action="setconfig", message=message):
        return

    data = await state.get_data()
    key = data.get("config_text_key")
    if not key or not RuntimeConfig.is_valid_text_key(key):
        await state.clear()
        return await message.answer(t(lang, "admin.config.unknown_key", setting=key or "?"), parse_mode="HTML")

    raw = (message.text or "").strip()
    if raw == "-":
        raw = ""  # explicit clear
    try:
        await RuntimeConfig.set_text(session, key, raw, updated_by=message.from_user.id)
    except ValueError:
        return await message.answer(t(lang, "admin.config.bad_value"), parse_mode="HTML")

    logger.info("Admin text-config change (button) admin_telegram_id=%s key=%s", message.from_user.id, key)
    await state.clear()
    await message.answer(
        t(lang, "admin.config.text_saved", setting=key),
        parse_mode="HTML",
        reply_markup=await _section_keyboard(session, lang, section_for_key(key) or "payments"),
    )


@admin_router.callback_query(F.data == "admin:config:fetchrate")
async def cb_admin_config_fetchrate(callback: CallbackQuery, session: AsyncSession):
    """Trigger a one-off USD→Toman fetch and report whether the source worked."""
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)

    from app.db.session import AsyncSessionLocal
    from app.services.exchange.rate_updater import ExchangeRateUpdater

    applied = None
    try:
        applied = await ExchangeRateUpdater.update_once(AsyncSessionLocal)
    except Exception:
        logger.exception("Manual exchange-rate fetch failed")

    if applied:
        await callback.answer(
            t(lang, "admin.config.rate_fetched", provider=settings.EXCHANGE_RATE_PROVIDER, rate=f"{applied:,}"),
            show_alert=True,
        )
    else:
        await callback.answer(t(lang, "admin.config.rate_failed"), show_alert=True)

    # Re-render the payments section so the (possibly updated) rate is visible.
    try:
        await callback.message.edit_text(
            t(lang, "admin.config.section_hint", section=t(lang, "admin.config.cat.payments")),
            parse_mode="HTML",
            reply_markup=await _section_keyboard(session, lang, "payments"),
        )
    except Exception:
        pass


# ── Premium emoji manager (tap an emoji → send your premium one → auto-id) ────

def _extract_custom_emoji_id(message: Message) -> str | None:
    """Pull the first ``custom_emoji_id`` out of a message's entities. Works for
    both normal and caption entities; needs no type check because only premium
    (custom) emoji entities carry that field."""
    for entities in (message.entities or [], getattr(message, "caption_entities", None) or []):
        for entity in entities:
            cid = getattr(entity, "custom_emoji_id", None)
            if cid:
                return cid
    return None


async def _emoji_manager_view(session: AsyncSession, lang: str):
    from app.services.config.premium_emoji_store import EMOJI_REGISTRY, PremiumEmojiStore

    enabled = (await RuntimeConfig.get_int(session, "premium_emoji_enabled")) == 1
    mapping = await PremiumEmojiStore.get_map(session)  # {plain_emoji: id}
    configured = {slug for slug, emoji, _ in EMOJI_REGISTRY if emoji in mapping}
    status = t(lang, "admin.emoji.status_on" if enabled else "admin.emoji.status_off")
    text = t(lang, "admin.emoji.hint", status=status)
    kb = get_admin_emoji_kb(lang, enabled=enabled, configured_slugs=configured)
    return text, kb


@admin_router.callback_query(F.data == "admin:emoji")
async def cb_admin_emoji(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    await state.clear()
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    text, kb = await _emoji_manager_view(session, lang)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data == "admin:emoji:toggle")
async def cb_admin_emoji_toggle(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    current = await RuntimeConfig.get_int(session, "premium_emoji_enabled")
    await RuntimeConfig.set_int(session, "premium_emoji_enabled", 0 if current == 1 else 1, updated_by=callback.from_user.id)
    text, kb = await _emoji_manager_view(session, lang)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:emoji:s:"))
async def cb_admin_emoji_slug(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    from app.services.config.premium_emoji_store import PremiumEmojiStore, emoji_for_slug, is_valid_slug

    slug = callback.data.split(":", 3)[3]
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    if not is_valid_slug(slug):
        return await callback.answer(t(lang, "admin.config.unknown_key", setting=slug), show_alert=True)
    emoji = emoji_for_slug(slug)
    current = await PremiumEmojiStore.get_id(session, slug)
    await state.update_data(emoji_slug=slug)
    await state.set_state(AdminStates.waiting_for_premium_emoji)
    await callback.message.edit_text(
        t(lang, "admin.emoji.set_prompt", emoji=emoji, current=current or "—"),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang, back="admin:emoji"),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_premium_emoji)
async def process_premium_emoji(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    admin_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(admin_user)
    if not await _guard_admin_mutation(admin_id=message.from_user.id, lang=lang, action="setemoji", message=message):
        return

    from app.services.config.premium_emoji_store import PremiumEmojiStore, emoji_for_slug, is_valid_slug

    data = await state.get_data()
    slug = data.get("emoji_slug")
    if not slug or not is_valid_slug(slug):
        await state.clear()
        return await message.answer(t(lang, "admin.config.unknown_key", setting=slug or "?"), parse_mode="HTML")
    emoji = emoji_for_slug(slug)

    raw = (message.text or "").strip()
    if raw == "-":
        await PremiumEmojiStore.set_id(session, slug, "", updated_by=message.from_user.id)
        await state.clear()
        text, kb = await _emoji_manager_view(session, lang)
        await message.answer(t(lang, "admin.emoji.cleared", emoji=emoji), parse_mode="HTML")
        return await message.answer(text, parse_mode="HTML", reply_markup=kb)

    custom_id = _extract_custom_emoji_id(message)
    if not custom_id:
        # Keep the state so the admin can simply resend a correct premium emoji.
        return await message.answer(t(lang, "admin.emoji.none_found"), parse_mode="HTML")

    await PremiumEmojiStore.set_id(session, slug, custom_id, updated_by=message.from_user.id)
    logger.info("Admin premium-emoji set admin_telegram_id=%s slug=%s", message.from_user.id, slug)
    await state.clear()
    text, kb = await _emoji_manager_view(session, lang)
    await message.answer(t(lang, "admin.emoji.saved", emoji=emoji, id=custom_id), parse_mode="HTML")
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# ── Forced channel join manager ───────────────────────────────────────────────

def _normalize_channel(raw: str) -> str:
    """Accept @username, bare username, a t.me link, or a numeric id; return the
    form Telegram's get_chat_member understands (@username or -100… id)."""
    raw = (raw or "").strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "telegram.me/"):
        if raw.lower().startswith(prefix):
            raw = "@" + raw[len(prefix):].strip("/")
            break
    if raw and not raw.startswith("@") and not raw.startswith("http") and not raw.lstrip("-").isdigit():
        raw = "@" + raw
    return raw


async def _join_manager_view(session: AsyncSession, lang: str):
    enabled = (await RuntimeConfig.get_int(session, "forced_join_enabled")) == 1
    channel = (await RuntimeConfig.get_text(session, "forced_join_channel") or "").strip()
    status = t(lang, "admin.join.status_on" if enabled else "admin.join.status_off")
    shown = channel or t(lang, "admin.join.none")
    text = t(lang, "admin.join.hint", status=status, channel=shown)
    kb = get_admin_join_kb(lang, enabled=enabled, has_channel=bool(channel))
    return text, kb


async def _refresh_join_cache() -> None:
    from app.bot.middlewares.forced_join import clear_membership_cache

    await clear_membership_cache()


@admin_router.callback_query(F.data == "admin:join")
async def cb_admin_join(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    await state.clear()
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    text, kb = await _join_manager_view(session, lang)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data == "admin:join:toggle")
async def cb_admin_join_toggle(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    current = await RuntimeConfig.get_int(session, "forced_join_enabled")
    if current != 1:
        channel = (await RuntimeConfig.get_text(session, "forced_join_channel") or "").strip()
        if not channel:
            return await callback.answer(t(lang, "admin.join.need_channel"), show_alert=True)
    await RuntimeConfig.set_int(session, "forced_join_enabled", 0 if current == 1 else 1, updated_by=callback.from_user.id)
    await _refresh_join_cache()
    text, kb = await _join_manager_view(session, lang)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data == "admin:join:setchannel")
async def cb_admin_join_setchannel(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    current = (await RuntimeConfig.get_text(session, "forced_join_channel") or "").strip() or t(lang, "admin.join.none")
    await state.set_state(AdminStates.waiting_for_join_channel)
    await callback.message.edit_text(
        t(lang, "admin.join.set_prompt", channel=current),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang, back="admin:join"),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin:join:clear")
async def cb_admin_join_clear(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    await RuntimeConfig.set_text(session, "forced_join_channel", "", updated_by=callback.from_user.id)
    await RuntimeConfig.set_int(session, "forced_join_enabled", 0, updated_by=callback.from_user.id)
    await _refresh_join_cache()
    text, kb = await _join_manager_view(session, lang)
    await callback.answer(t(lang, "admin.join.cleared"), show_alert=False)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@admin_router.message(AdminStates.waiting_for_join_channel)
async def process_join_channel(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    admin_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(admin_user)
    if not await _guard_admin_mutation(admin_id=message.from_user.id, lang=lang, action="setjoin", message=message):
        return

    raw = (message.text or "").strip()
    if raw == "-":
        await RuntimeConfig.set_text(session, "forced_join_channel", "", updated_by=message.from_user.id)
        await RuntimeConfig.set_int(session, "forced_join_enabled", 0, updated_by=message.from_user.id)
        await _refresh_join_cache()
        await state.clear()
        text, kb = await _join_manager_view(session, lang)
        await message.answer(t(lang, "admin.join.cleared"), parse_mode="HTML")
        return await message.answer(text, parse_mode="HTML", reply_markup=kb)

    channel = _normalize_channel(raw)
    try:
        await RuntimeConfig.set_text(session, "forced_join_channel", channel, updated_by=message.from_user.id)
    except ValueError:
        return await message.answer(t(lang, "admin.config.bad_value"), parse_mode="HTML")
    await _refresh_join_cache()
    logger.info("Admin set forced-join channel admin_telegram_id=%s channel=%s", message.from_user.id, channel)
    await state.clear()
    text, kb = await _join_manager_view(session, lang)
    await message.answer(t(lang, "admin.join.saved", channel=channel), parse_mode="HTML")
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# ── AI connection diagnostic ──────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:diag:ai")
async def cb_admin_diag_ai(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Call the model with a tiny prompt and surface the RESULT or the EXACT
    error right in Telegram — so the cause (bad model name, API key, quota, or
    no network route to Google) is visible without shell/log access."""
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    model = settings.GEMINI_MODEL_NORMAL

    await callback.answer()
    await callback.message.edit_text(t(lang, "admin.diag.testing", model=model), parse_mode="HTML")

    from app.services.ai.antigravity import AntigravityProvider
    from app.services.ai.provider import AIMessage

    try:
        provider = AntigravityProvider()
        response = await asyncio.wait_for(
            provider.generate_text(
                model_name=model,
                messages=[AIMessage(role="user", content="Reply with the single word: OK")],
                system_instruction="You are a health check. Reply with one short word.",
                max_tokens=20,
            ),
            timeout=30,
        )
        reply_preview = (response.text or "").strip()[:80] or "—"
        text = t(lang, "admin.diag.ok", model=model, tokens=response.tokens_used, reply=html.escape(reply_preview))
    except Exception as exc:  # noqa: BLE001 — we WANT to show whatever broke
        err = f"{type(exc).__name__}: {exc}"
        logger.warning("Admin AI diagnostic failed model=%s err=%s", model, err)
        text = t(lang, "admin.diag.fail", model=model, error=html.escape(err[:600]))

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang, back="admin:config"),
    )


def _pack_label(lang: str, code: str | None) -> str:
    if not code:
        return "?"
    label = t(lang, f"packs.{code}")
    return label if label != f"packs.{code}" else code


@admin_router.callback_query(F.data == "admin:cardpay:list")
async def cb_admin_cardpay_list(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(admin_user)
    rows = (
        await session.scalars(
            select(PaymentTransaction)
            .where(
                PaymentTransaction.provider == "card_to_card",
                PaymentTransaction.status == TransactionStatus.PENDING,
            )
            .order_by(PaymentTransaction.created_at.asc())
            .limit(20)
        )
    ).all()

    builder = InlineKeyboardBuilder()
    if not rows:
        await callback.message.edit_text(t(lang, "admin.cardpay.empty"), parse_mode="HTML", reply_markup=get_back_to_admin_kb(lang))
        return await callback.answer()

    for tx in rows:
        payload = tx.raw_payload or {}
        code = payload.get("product_code")
        name = payload.get("telegram_id", tx.user_id)
        builder.row(
            InlineKeyboardButton(
                text=t(lang, "admin.cardpay.item", tx=tx.id, name=name, pack=_pack_label(lang, code))[:64],
                callback_data=f"admin:cardpay:view:{tx.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text=t(lang, "buttons.refresh"), callback_data="admin:cardpay:list"),
        InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data="admin:main"),
    )
    await callback.message.edit_text(t(lang, "admin.cardpay.title"), parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:cardpay:view:"))
async def cb_admin_cardpay_view(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(admin_user)
    tx_id = int(callback.data.split(":")[3])
    tx = await session.get(PaymentTransaction, tx_id)
    if not tx or tx.provider != "card_to_card":
        return await callback.answer(t(lang, "admin.cardpay.not_found"), show_alert=True)

    payload = tx.raw_payload or {}
    code = payload.get("product_code")
    product = get_product(code)
    buyer = await session.get(User, tx.user_id)
    name = html.escape((buyer.username or buyer.first_name or "unknown")) if buyer else "?"
    usd_price = product.usd_price if product else tx.amount
    rate = await RuntimeConfig.get_int(session, "usd_toman_rate")
    toman_line = t(lang, "purchase.card.toman_line", toman=f"{int(round(usd_price * rate)):,}") if rate > 0 else ""
    caption = t(
        lang,
        "admin.cardpay.detail",
        tx=tx.id,
        telegram_id=payload.get("telegram_id", tx.user_id),
        name=name,
        pack=_pack_label(lang, code),
        price=f"{usd_price:.2f}",
        toman_line=toman_line,
        created=tx.created_at.strftime("%Y-%m-%d %H:%M"),
    )
    kb = InlineKeyboardBuilder()
    if tx.status == TransactionStatus.PENDING:
        kb.row(
            InlineKeyboardButton(text=t(lang, "buttons.approve"), callback_data=f"admin:cardpay:approve:{tx.id}"),
            InlineKeyboardButton(text=t(lang, "buttons.reject"), callback_data=f"admin:cardpay:reject:{tx.id}"),
        )
    kb.row(InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data="admin:cardpay:list"))

    receipt = payload.get("receipt_file_id")
    await callback.answer()
    if receipt:
        try:
            return await callback.message.answer_photo(photo=receipt, caption=caption, parse_mode="HTML", reply_markup=kb.as_markup())
        except Exception:
            logger.warning("Could not render receipt photo for tx=%s", tx.id, exc_info=True)
    await callback.message.answer(caption, parse_mode="HTML", reply_markup=kb.as_markup())


@admin_router.callback_query(F.data.startswith("admin:cardpay:approve:"))
async def cb_admin_cardpay_approve(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(admin_user)
    if not await _guard_admin_mutation(admin_id=callback.from_user.id, lang=lang, action="cardpay", callback=callback):
        return
    tx_id = int(callback.data.split(":")[3])

    # Lock the transaction row so two admins can't approve the same payment.
    tx = await session.scalar(
        select(PaymentTransaction).where(PaymentTransaction.id == tx_id).with_for_update()
    )
    if not tx or tx.provider != "card_to_card":
        return await callback.answer(t(lang, "admin.cardpay.not_found"), show_alert=True)
    if tx.status != TransactionStatus.PENDING:
        return await callback.answer(t(lang, "admin.cardpay.already", tx=tx.id), show_alert=True)

    payload = tx.raw_payload or {}
    product = get_product(payload.get("product_code"))
    buyer = await session.get(User, tx.user_id)
    if not product or not buyer:
        return await callback.answer(t(lang, "admin.cardpay.not_found"), show_alert=True)

    buyer_lang = buyer.language or "fa"
    billing = BillingService(session)
    try:
        grant_text = await apply_product(
            billing,
            user_id=buyer.id,
            product=product,
            payment_ref=f"card_{tx.id}",
            price_label=f"${product.usd_price}",
            lang=buyer_lang,
        )
    except Exception as exc:
        from app.core.exceptions import DuplicateTransactionError
        if isinstance(exc, DuplicateTransactionError):
            tx.status = TransactionStatus.COMPLETED
            await session.commit()
            return await callback.answer(t(lang, "admin.cardpay.already", tx=tx.id), show_alert=True)
        logger.error("Card payment approve failed tx=%s: %s", tx.id, exc, exc_info=True)
        await session.rollback()
        return await callback.answer(_admin_action_error(lang), show_alert=True)

    tx.status = TransactionStatus.COMPLETED
    tx.credits_granted = product.normal_credits or product.vip_credits or 0
    await session.commit()

    try:
        await callback.bot.send_message(
            chat_id=payload.get("telegram_id", buyer.telegram_id),
            text=t(buyer_lang, "purchase.card.approved_user", grant=grant_text),
            parse_mode="HTML",
        )
    except Exception:
        logger.warning("Could not notify buyer of approved card payment tx=%s", tx.id)

    await callback.answer(
        t(lang, "admin.cardpay.approved", telegram_id=payload.get("telegram_id", buyer.telegram_id)),
        show_alert=True,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=get_back_to_admin_kb(lang, back="admin:cardpay:list"))
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin:cardpay:reject:"))
async def cb_admin_cardpay_reject(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(admin_user)
    if not await _guard_admin_mutation(admin_id=callback.from_user.id, lang=lang, action="cardpay", callback=callback):
        return
    tx_id = int(callback.data.split(":")[3])

    tx = await session.scalar(
        select(PaymentTransaction).where(PaymentTransaction.id == tx_id).with_for_update()
    )
    if not tx or tx.provider != "card_to_card":
        return await callback.answer(t(lang, "admin.cardpay.not_found"), show_alert=True)
    if tx.status != TransactionStatus.PENDING:
        return await callback.answer(t(lang, "admin.cardpay.already", tx=tx.id), show_alert=True)

    payload = tx.raw_payload or {}
    buyer = await session.get(User, tx.user_id)
    buyer_lang = (buyer.language if buyer else None) or "fa"
    tx.status = TransactionStatus.FAILED
    await session.commit()

    try:
        await callback.bot.send_message(
            chat_id=payload.get("telegram_id", buyer.telegram_id if buyer else None),
            text=t(buyer_lang, "purchase.card.rejected_user"),
            parse_mode="HTML",
        )
    except Exception:
        logger.warning("Could not notify buyer of rejected card payment tx=%s", tx.id)

    await callback.answer(t(lang, "admin.cardpay.rejected", tx=tx.id), show_alert=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_back_to_admin_kb(lang, back="admin:cardpay:list"))
    except Exception:
        pass


@admin_router.callback_query(F.data == "admin:main")
async def cb_admin_main(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    await state.clear()
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    await callback.message.edit_text(t(lang, "admin.panel_title"), parse_mode="HTML", reply_markup=get_admin_main_kb(lang))
    await callback.answer()


@admin_router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    stats = await _admin_service(session).get_system_stats()
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    await callback.message.edit_text(_format_stats(stats), parse_mode="HTML", reply_markup=get_back_to_admin_kb(lang))
    await callback.answer()


@admin_router.callback_query(F.data == "admin:abuse")
async def cb_admin_abuse(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    overview = await _admin_service(session).get_abuse_overview()
    await callback.message.edit_text(
        _format_abuse_overview(lang, overview),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:users:page:"))
async def cb_admin_users(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)

    parts = callback.data.split(":")
    page, search = _parse_page_search(parts)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    await _render_user_page(callback, _admin_service(session), page, search, _lang(user))
    await callback.answer()


@admin_router.callback_query(F.data == "admin:users:search")
async def cb_admin_users_search(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    await state.set_state(AdminStates.waiting_for_user_search)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    await callback.message.edit_text(
        "<b>User Search</b>\n\nSend Telegram ID or username to search.",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(_lang(user)),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_user_search)
async def process_user_search(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    await state.clear()
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    await _render_user_page(message, _admin_service(session), page=1, search=(message.text or "").strip(), lang=_lang(user))


@admin_router.callback_query(F.data.regexp(r"^admin:user:\d+:page:\d+(?::search:.*)?$"))
async def cb_admin_user_detail(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    parts = callback.data.split(":")
    telegram_id = int(parts[2])
    page, search = _parse_page_search(parts)
    user = await _admin_service(session).get_user_details(telegram_id)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    await callback.message.edit_text(
        _format_user_detail(user),
        parse_mode="HTML",
        reply_markup=get_user_manage_kb(user, _lang(admin_user), page=page, search=search),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:user:add_normal:") | F.data.startswith("admin:user:add_vip:"))
async def cb_admin_add_credits_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)

    wallet_type = WalletType.NORMAL if ":add_normal:" in callback.data else WalletType.VIP
    parts = callback.data.split(":")
    telegram_id = int(parts[3])
    page, search = _parse_page_search(parts)
    await state.update_data(target_tg_id=telegram_id, wallet_type=wallet_type.value, source_page=page, source_search=search)
    await state.set_state(AdminStates.waiting_for_credit_amount)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(admin_user)
    await callback.message.edit_text(
        t(lang, "admin.add_credits_prompt", wallet=wallet_type.value.lower(), telegram_id=telegram_id),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang, back=_user_detail_callback(telegram_id, page, search)),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_credit_amount)
async def process_add_credit_amount(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    admin_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(admin_user)
    if not await _guard_admin_mutation(admin_id=message.from_user.id, lang=lang, action="credit_grant", message=message):
        return
    if not message.text or not message.text.isdigit():
        return await message.answer(t(lang, "admin.enter_positive_amount"))

    data = await state.get_data()
    wallet_type = WalletType(data["wallet_type"])
    target_tg_id = int(data["target_tg_id"])
    source_page = int(data.get("source_page", 1))
    source_search = data.get("source_search")
    back_cb = _user_detail_callback(target_tg_id, source_page, source_search)
    service = _admin_service(session)
    try:
        await service.add_credits_to_user(
            admin_telegram_id=message.from_user.id,
            target_telegram_id=target_tg_id,
            amount=int(message.text),
            wallet_type=wallet_type,
        )
        user = await service.get_user_details(target_tg_id)
    except Exception as e:
        logger.error("Admin credit action failed admin_id=%s target_tg_id=%s: %s", message.from_user.id, target_tg_id, e, exc_info=True)
        await AbuseGuardService.record_failure(subject="admin_credit_grant", subject_id=message.from_user.id)
        await session.rollback()
        await state.clear()
        return await message.answer(_admin_action_error(lang), reply_markup=get_back_to_admin_kb(lang, back=back_cb))

    await state.clear()
    await message.answer(
        f"{_admin_saved(lang)}\n\n{_format_user_detail(user)}",
        parse_mode="HTML",
        reply_markup=get_user_manage_kb(user, lang, page=source_page, search=source_search),
    )


@admin_router.callback_query(F.data.startswith("admin:user:vip:"))
async def cb_admin_give_vip_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    parts = callback.data.split(":")
    telegram_id = int(parts[3])
    page, search = _parse_page_search(parts)
    await state.update_data(target_tg_id=telegram_id, source_page=page, source_search=search)
    await state.set_state(AdminStates.waiting_for_vip_days)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(admin_user)
    await callback.message.edit_text(
        t(lang, "admin.vip_days_prompt", telegram_id=telegram_id),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang, back=_user_detail_callback(telegram_id, page, search)),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_vip_days)
async def process_vip_days(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    admin_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(admin_user)
    if not await _guard_admin_mutation(admin_id=message.from_user.id, lang=lang, action="vip_grant", message=message):
        return
    if not message.text or not message.text.isdigit():
        return await message.answer(t(lang, "admin.enter_positive_days"))

    data = await state.get_data()
    target_tg_id = int(data["target_tg_id"])
    source_page = int(data.get("source_page", 1))
    source_search = data.get("source_search")
    back_cb = _user_detail_callback(target_tg_id, source_page, source_search)
    service = _admin_service(session)
    try:
        await service.grant_vip_to_user(message.from_user.id, target_tg_id, int(message.text))
        user = await service.get_user_details(target_tg_id)
    except Exception as e:
        logger.error("Admin VIP action failed admin_id=%s target_tg_id=%s: %s", message.from_user.id, target_tg_id, e, exc_info=True)
        await AbuseGuardService.record_failure(subject="admin_vip_grant", subject_id=message.from_user.id)
        await session.rollback()
        await state.clear()
        return await message.answer(_admin_action_error(lang), reply_markup=get_back_to_admin_kb(lang, back=back_cb))

    await state.clear()
    await message.answer(
        f"{t(lang, 'admin.vip_updated')}\n\n{_format_user_detail(user)}",
        parse_mode="HTML",
        reply_markup=get_user_manage_kb(user, lang, page=source_page, search=source_search),
    )


@admin_router.callback_query(F.data.startswith("admin:user:ban:"))
async def cb_admin_ban_toggle(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    parts = callback.data.split(":")
    telegram_id = int(parts[3])
    page, search = _parse_page_search(parts)
    service = _admin_service(session)
    user = await service.get_user_details(telegram_id)
    updated_user = await service.set_user_ban_status(telegram_id, not user.is_banned)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    await callback.message.edit_text(
        _format_user_detail(updated_user),
        parse_mode="HTML",
        reply_markup=get_user_manage_kb(updated_user, _lang(admin_user), page=page, search=search),
    )
    await callback.answer(t(_lang(admin_user), "admin.user_updated"))


@admin_router.callback_query(F.data == "admin:codes")
async def cb_admin_codes(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    await callback.message.edit_text("<b>Gift / Discount Codes</b>", parse_mode="HTML", reply_markup=get_code_menu_kb(_lang(user)))
    await callback.answer()


@admin_router.callback_query(F.data == "admin:codes:create")
async def cb_admin_codes_create(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    await callback.message.edit_text(
        "<b>Create Code</b>\n\nChoose the code type.",
        parse_mode="HTML",
        reply_markup=get_code_kind_kb("fa"),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:codes:kind:"))
async def cb_admin_codes_kind(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    kind = callback.data.split(":")[-1]
    await state.update_data(code_kind=kind)
    await state.set_state(AdminStates.waiting_for_code_amount)
    await callback.message.edit_text(
        "<b>Create Code</b>\n\nSend the value:\n"
        "- normal credits\n- vip credits\n- vip days\n- or discount percent",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb("fa"),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_code_amount)
async def process_code_amount(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    if not message.text or not message.text.isdigit():
        return await message.answer("Please send a positive integer value.")
    await state.update_data(code_amount=int(message.text))
    await state.set_state(AdminStates.waiting_for_code_expiry_days)
    await message.answer("How many days should this code stay valid? Send 0 for no expiry.")


@admin_router.message(AdminStates.waiting_for_code_expiry_days)
async def process_code_expiry(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    if not message.text or not message.text.isdigit():
        return await message.answer("Please send a non-negative integer.")
    await state.update_data(expiry_days=int(message.text))
    await state.set_state(AdminStates.waiting_for_code_max_uses)
    await message.answer("Maximum total uses?")


@admin_router.message(AdminStates.waiting_for_code_max_uses)
async def process_code_max_uses(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    if not message.text or not message.text.isdigit():
        return await message.answer("Please send a positive integer.")
    await state.update_data(max_uses=int(message.text))
    await state.set_state(AdminStates.waiting_for_code_max_uses_per_user)
    await message.answer("Maximum uses per user?")


@admin_router.message(AdminStates.waiting_for_code_max_uses_per_user)
async def process_code_max_uses_per_user(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    if not message.text or not message.text.isdigit():
        return await message.answer("Please send a positive integer.")
    await state.update_data(max_uses_per_user=int(message.text))
    await message.answer("Choose how to create the code value.", reply_markup=get_code_generation_kb("fa"))


@admin_router.callback_query(F.data.startswith("admin:codes:generate:"))
async def cb_admin_codes_generate(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(user)
    if not await _guard_admin_mutation(admin_id=callback.from_user.id, lang=lang, action="code_create", callback=callback):
        return
    mode = callback.data.split(":")[-1]
    if mode == "auto":
        await _finalize_code_creation(callback.message, session, state, manual_code=None, admin_telegram_id=callback.from_user.id)
        await callback.answer("Code created")
        return

    await state.set_state(AdminStates.waiting_for_manual_code)
    await callback.message.edit_text(
        "<b>Create Code</b>\n\nSend the manual code text.",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb("fa"),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_manual_code)
async def process_manual_code(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    await _finalize_code_creation(message, session, state, manual_code=(message.text or "").strip(), admin_telegram_id=message.from_user.id)


async def _finalize_code_creation(
    target: Message,
    session: AsyncSession,
    state: FSMContext,
    *,
    manual_code: str | None,
    admin_telegram_id: int,
) -> None:
    data = await state.get_data()
    service = _admin_service(session)
    kind = PromoCodeKind(data["code_kind"])
    amount = int(data["code_amount"])
    expiry_days = int(data["expiry_days"])
    expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days) if expiry_days > 0 else None
    code = (manual_code or secrets.token_hex(4)).upper()

    kwargs = {
        "normal_credits": 0,
        "vip_credits": 0,
        "vip_days": 0,
        "discount_percent": 0,
    }
    if kind == PromoCodeKind.GIFT_NORMAL_CREDITS:
        kwargs["normal_credits"] = amount
    elif kind == PromoCodeKind.GIFT_VIP_CREDITS:
        kwargs["vip_credits"] = amount
    elif kind == PromoCodeKind.GIFT_VIP_DAYS:
        kwargs["vip_days"] = amount
    else:
        kwargs["discount_percent"] = amount

    promo = await service.create_promo_code(
        admin_telegram_id=admin_telegram_id,
        kind=kind,
        code=code,
        max_uses=int(data["max_uses"]),
        max_uses_per_user=int(data["max_uses_per_user"]),
        expires_at=expires_at,
        **kwargs,
    )
    await state.clear()
    await target.answer(
        "<b>Code Created</b>\n\n"
        f"Code: <code>{promo.code}</code>\n"
        f"Kind: <code>{promo.kind.value}</code>\n"
        f"Max uses: <code>{promo.max_uses}</code>\n"
        f"Max uses per user: <code>{promo.max_uses_per_user}</code>",
        parse_mode="HTML",
        reply_markup=get_code_detail_kb(promo.id, "fa"),
    )


@admin_router.callback_query(F.data == "admin:codes:list")
async def cb_admin_codes_list(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    codes = await _admin_service(session).list_promo_codes(active_only=False)
    await callback.message.edit_text(
        "<b>Codes</b>\n\nSelect a code to inspect or disable it.",
        parse_mode="HTML",
        reply_markup=get_codes_list_kb(codes, "fa"),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:codes:view:"))
async def cb_admin_codes_view(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    code_id = int(callback.data.split(":")[-1])
    usage = await _admin_service(session).get_promo_usage(code_id)
    promo = usage["promo"]
    await callback.message.edit_text(
        "<b>Code Details</b>\n\n"
        f"Code: <code>{promo.code}</code>\n"
        f"Kind: <code>{promo.kind.value}</code>\n"
        f"Normal credits: <code>{promo.normal_credits}</code>\n"
        f"VIP credits: <code>{promo.vip_credits}</code>\n"
        f"VIP days: <code>{promo.vip_days}</code>\n"
        f"Discount: <code>{promo.discount_percent}%</code>\n"
        f"Uses: <code>{promo.used_count}/{promo.max_uses}</code>\n"
        f"Active: <code>{promo.is_active}</code>",
        parse_mode="HTML",
        reply_markup=get_code_detail_kb(code_id, "fa"),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:codes:disable:"))
async def cb_admin_codes_disable(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if not await _guard_admin_mutation(admin_id=callback.from_user.id, lang=_lang(user), action="code_disable", callback=callback):
        return
    code_id = int(callback.data.split(":")[-1])
    promo = await _admin_service(session).disable_promo_code(code_id)
    await callback.message.edit_text(
        f"<b>Code Disabled</b>\n\n<code>{promo.code}</code> is now inactive.",
        parse_mode="HTML",
        reply_markup=get_code_menu_kb("fa"),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:codes:usage:"))
async def cb_admin_codes_usage(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    code_id = int(callback.data.split(":")[-1])
    usage = await _admin_service(session).get_promo_usage(code_id)
    lines = [
        "<b>Code Usage</b>",
        "",
        f"Used count: <code>{usage['used_count']}</code>",
    ]
    for redemption in usage["redemptions"][:10]:
        lines.append(f"user_id=<code>{redemption.user_id}</code> used=<code>{redemption.used_count}</code>")
    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=get_back_to_admin_kb("fa"))
    await callback.answer()


@admin_router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.edit_text(
        "<b>Broadcast</b>\n\nSend the message you want to broadcast.",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb("fa"),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast_message(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
        
    stmt = select(User.telegram_id).where(User.telegram_id.is_not(None))
    user_ids = (await session.execute(stmt)).scalars().all()
    
    success_count = 0
    fail_count = 0
    
    status_msg = await message.answer(
        f"⏳ <b>Broadcast Started</b>\nSending to {len(user_ids)} users...",
        parse_mode="HTML",
    )
    
    for uid in user_ids:
        try:
            await message.send_copy(chat_id=uid)
            success_count += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.send_copy(chat_id=uid)
                success_count += 1
            except Exception:
                fail_count += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            fail_count += 1
        except Exception:
            fail_count += 1
            
    await state.clear()
    await status_msg.edit_text(
        "<b>Broadcast Finished</b> ✅\n\n"
        f"Success: <code>{success_count}</code>\n"
        f"Failed (Blocked/Deleted): <code>{fail_count}</code>",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb("fa"),
    )


@admin_router.callback_query(F.data == "admin:broadcast:stop")
async def cb_admin_broadcast_stop(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    await BroadcastControlService.stop(callback.from_user.id)
    await callback.answer(t(_lang(user), "admin.broadcast_stopped"), show_alert=False)


@admin_router.callback_query(F.data == "admin:pricing")
async def cb_admin_pricing(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    features = (await session.scalars(select(FeatureConfig).order_by(FeatureConfig.name.asc()))).all()
    lines = ["<b>Pricing / Config</b>", ""]
    for feature in features:
        lines.append(
            f"{feature.name.value}: cost=<code>{feature.credit_cost}</code> model=<code>{feature.model_name}</code>"
        )
    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=get_back_to_admin_kb("fa"))
    await callback.answer()


@admin_router.callback_query(F.data == "admin:noop")
async def cb_admin_noop(callback: CallbackQuery):
    await callback.answer()
