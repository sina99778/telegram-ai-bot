from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_kb import (
    get_admin_main_kb,
    get_admin_users_kb,
    get_back_to_admin_kb,
    get_code_detail_kb,
    get_code_generation_kb,
    get_code_kind_kb,
    get_code_menu_kb,
    get_codes_list_kb,
    get_user_manage_kb,
)
from app.core.access import is_configured_admin
from app.core.enums import PromoCodeKind, WalletType
from app.core.i18n import t
from app.db.models import FeatureConfig, User
from app.services.admin.admin_service import AdminService
from app.services.billing.billing_service import BillingService

admin_router = Router(name="admin")


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


async def _is_admin(user_id: int, session: AsyncSession) -> bool:
    return is_configured_admin(user_id)


def _admin_service(session: AsyncSession) -> AdminService:
    return AdminService(session, BillingService(session))


def _format_user_detail(user: User) -> str:
    display_name = user.username or user.first_name or "unknown"
    vip_until = user.active_vip_until
    vip_status = f"ACTIVE until {vip_until:%Y-%m-%d}" if user.has_active_vip and vip_until else (
        "ACTIVE" if user.has_active_vip else "INACTIVE"
    )
    ban_status = "BANNED" if user.is_banned else "ACTIVE"
    return (
        "<b>User Management</b>\n\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Name: {display_name}\n"
        f"Normal credits: <code>{user.normal_credits}</code>\n"
        f"VIP credits: <code>{user.vip_credits}</code>\n"
        f"VIP status: <b>{vip_status}</b>\n"
        f"Ban status: <b>{ban_status}</b>"
    )


def _admin_action_error(lang: str) -> str:
    return t(lang, "admin.action_failed")


def _admin_saved(lang: str) -> str:
    return t(lang, "admin.action_saved")


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


async def _render_user_page(
    message: Message | CallbackQuery,
    service: AdminService,
    page: int,
    search: str | None = None,
    lang: str = "fa",
) -> None:
    result = await service.list_users(page=page, search=search)
    text = (
        "<b>Users</b>\n\n"
        "Each row shows: telegram_id | username/name | normal credits | vip credits | VIP status | ban status\n"
    )
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


@admin_router.callback_query(F.data.startswith("admin:users:page:"))
async def cb_admin_users(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)

    parts = callback.data.split(":")
    page = int(parts[3])
    search = parts[5] if len(parts) > 5 and parts[4] == "search" and parts[5] != "-" else None
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


@admin_router.callback_query(F.data.startswith("admin:user:") & F.data.contains(":page:"))
async def cb_admin_user_detail(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    parts = callback.data.split(":")
    telegram_id = int(parts[2])
    page = int(parts[4])
    search = parts[6] if len(parts) > 6 and parts[5] == "search" and parts[6] != "-" else None
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
    telegram_id = int(callback.data.split(":")[-1])
    await state.update_data(target_tg_id=telegram_id, wallet_type=wallet_type.value)
    await state.set_state(AdminStates.waiting_for_credit_amount)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(admin_user)
    await callback.message.edit_text(
        t(lang, "admin.add_credits_prompt", wallet=wallet_type.value.lower(), telegram_id=telegram_id),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_credit_amount)
async def process_add_credit_amount(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    admin_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(admin_user)
    if not message.text or not message.text.isdigit():
        return await message.answer(t(lang, "admin.enter_positive_amount"))

    data = await state.get_data()
    wallet_type = WalletType(data["wallet_type"])
    target_tg_id = int(data["target_tg_id"])
    service = _admin_service(session)
    try:
        await service.add_credits_to_user(
            admin_telegram_id=message.from_user.id,
            target_telegram_id=target_tg_id,
            amount=int(message.text),
            wallet_type=wallet_type,
        )
        user = await service.get_user_details(target_tg_id)
    except Exception:
        await session.rollback()
        await state.clear()
        return await message.answer(_admin_action_error(lang), reply_markup=get_back_to_admin_kb(lang))

    await state.clear()
    await message.answer(
        f"{_admin_saved(lang)}\n\n{_format_user_detail(user)}",
        parse_mode="HTML",
        reply_markup=get_user_manage_kb(user, lang),
    )


@admin_router.callback_query(F.data.startswith("admin:user:vip:"))
async def cb_admin_give_vip_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    telegram_id = int(callback.data.split(":")[-1])
    await state.update_data(target_tg_id=telegram_id)
    await state.set_state(AdminStates.waiting_for_vip_days)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    lang = _lang(admin_user)
    await callback.message.edit_text(
        t(lang, "admin.vip_days_prompt", telegram_id=telegram_id),
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb(lang),
    )
    await callback.answer()


@admin_router.message(AdminStates.waiting_for_vip_days)
async def process_vip_days(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_admin(message.from_user.id, session):
        return
    admin_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    lang = _lang(admin_user)
    if not message.text or not message.text.isdigit():
        return await message.answer(t(lang, "admin.enter_positive_days"))

    data = await state.get_data()
    target_tg_id = int(data["target_tg_id"])
    service = _admin_service(session)
    try:
        await service.grant_vip_to_user(message.from_user.id, target_tg_id, int(message.text))
        user = await service.get_user_details(target_tg_id)
    except Exception:
        await session.rollback()
        await state.clear()
        return await message.answer(_admin_action_error(lang), reply_markup=get_back_to_admin_kb(lang))

    await state.clear()
    await message.answer(
        f"{t(lang, 'admin.vip_updated')}\n\n{_format_user_detail(user)}",
        parse_mode="HTML",
        reply_markup=get_user_manage_kb(user, lang),
    )


@admin_router.callback_query(F.data.startswith("admin:user:ban:"))
async def cb_admin_ban_toggle(callback: CallbackQuery, session: AsyncSession):
    if not await _is_admin(callback.from_user.id, session):
        return await callback.answer(t("fa", "errors.access_denied"), show_alert=True)
    telegram_id = int(callback.data.split(":")[-1])
    service = _admin_service(session)
    user = await service.get_user_details(telegram_id)
    updated_user = await service.set_user_ban_status(telegram_id, not user.is_banned)
    admin_user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    await callback.message.edit_text(
        _format_user_detail(updated_user),
        parse_mode="HTML",
        reply_markup=get_user_manage_kb(updated_user, _lang(admin_user)),
    )
    await callback.answer("Updated")


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
    for uid in user_ids:
        try:
            await message.send_copy(chat_id=uid)
            success_count += 1
        except Exception:
            fail_count += 1
    await state.clear()
    await message.answer(
        "<b>Broadcast Finished</b>\n\n"
        f"Success: <code>{success_count}</code>\n"
        f"Failed: <code>{fail_count}</code>",
        parse_mode="HTML",
        reply_markup=get_back_to_admin_kb("fa"),
    )


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
