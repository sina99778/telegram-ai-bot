from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    get_cancel_promo_keyboard,
    get_checkout_keyboard,
    get_normal_credit_packs_keyboard,
    get_profile_keyboard,
    get_support_menu_keyboard,
    get_vip_access_packs_keyboard,
    get_vip_credit_packs_keyboard,
    get_vip_menu_keyboard,
    get_wallet_menu_keyboard,
)
from app.core.enums import LedgerEntryType, WalletType
from app.core.i18n import t
from app.db.models import User
from app.db.repositories.chat_repo import ChatRepository
from app.services.admin.admin_service import AdminService
from app.services.billing.billing_service import BillingService
from app.services.payment_service import NowPaymentsService
from app.services.purchase.catalog import build_order_id, get_product

callback_router = Router(name="callbacks")


class PromoStates(StatesGroup):
    waiting_for_code = State()


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


def _format_profile(user: User) -> str:
    lang = _lang(user)
    vip_status = (
        t(lang, "profile.vip.active_until", date=user.vip_expire_date.strftime("%Y-%m-%d"))
        if user.has_active_vip and user.vip_expire_date
        else (t(lang, "profile.vip.active") if user.has_active_vip else t(lang, "profile.vip.inactive"))
    )
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    memory = t(lang, "profile.memory.keep") if user.keep_chat_history else t(lang, "profile.memory.clear")
    return "\n".join(
        [
            t(lang, "profile.title"),
            "",
            t(lang, "profile.name", value=user.first_name or user.username or "unknown"),
            t(lang, "profile.id", value=user.telegram_id),
            t(lang, "profile.normal_credits", value=user.normal_credits),
            t(lang, "profile.vip_credits", value=user.vip_credits),
            t(lang, "profile.vip_status", value=vip_status),
            t(lang, "profile.model", value=current_model),
            t(lang, "profile.memory", value=memory),
        ]
    )


@callback_router.callback_query(F.data == "wallet:open")
async def cb_wallet_open(callback: CallbackQuery, db_user: User | None = None):
    lang = _lang(db_user)
    await callback.message.edit_text(
        t(lang, "wallet.menu_intro"),
        parse_mode="HTML",
        reply_markup=get_wallet_menu_keyboard(lang),
    )
    await callback.answer()


@callback_router.callback_query(F.data == "wallet:buy_normal")
async def cb_wallet_buy_normal(callback: CallbackQuery, db_user: User | None = None):
    lang = _lang(db_user)
    await callback.message.edit_text(
        t(lang, "purchase.normal_intro"),
        parse_mode="HTML",
        reply_markup=get_normal_credit_packs_keyboard(lang),
    )
    await callback.answer()


@callback_router.callback_query(F.data == "wallet:buy_vip")
async def cb_wallet_buy_vip(callback: CallbackQuery, db_user: User | None = None):
    lang = _lang(db_user)
    await callback.message.edit_text(
        t(lang, "purchase.vip_intro"),
        parse_mode="HTML",
        reply_markup=get_vip_credit_packs_keyboard(lang),
    )
    await callback.answer()


@callback_router.callback_query(F.data == "wallet:buy_access")
async def cb_wallet_buy_access(callback: CallbackQuery, db_user: User | None = None):
    lang = _lang(db_user)
    await callback.message.edit_text(
        t(lang, "purchase.access_intro"),
        parse_mode="HTML",
        reply_markup=get_vip_access_packs_keyboard(lang),
    )
    await callback.answer()


@callback_router.callback_query(F.data == "vip:open")
async def cb_vip_open(callback: CallbackQuery, db_user: User | None = None):
    lang = _lang(db_user)
    await callback.message.edit_text(
        t(lang, "vip.menu"),
        parse_mode="HTML",
        reply_markup=get_vip_menu_keyboard(lang),
    )
    await callback.answer()


@callback_router.callback_query(F.data == "vip:benefits")
async def cb_vip_benefits(callback: CallbackQuery, db_user: User | None = None):
    lang = _lang(db_user)
    await callback.message.edit_text(
        t(lang, "vip.benefits"),
        parse_mode="HTML",
        reply_markup=get_vip_menu_keyboard(lang),
    )
    await callback.answer()


@callback_router.callback_query(F.data == "support:back")
async def cb_support_back(callback: CallbackQuery, db_user: User | None = None):
    lang = _lang(db_user)
    await callback.message.edit_text(
        t(lang, "support.menu"),
        parse_mode="HTML",
        reply_markup=get_support_menu_keyboard(lang),
    )
    await callback.answer()


@callback_router.callback_query(F.data.startswith("purchase:"))
async def cb_purchase_checkout(callback: CallbackQuery, db_user: User | None = None):
    lang = _lang(db_user)
    code = callback.data.split(":", 1)[1]
    product = get_product(code)
    if not product:
        return await callback.answer(t(lang, "purchase.not_found"), show_alert=True)

    bot_info = await callback.bot.get_me()
    bot_link = f"https://t.me/{bot_info.username}" if bot_info.username else "https://t.me"
    order_id = build_order_id(code, callback.from_user.id, int(datetime.now(timezone.utc).timestamp()))
    invoice_url = await NowPaymentsService.create_invoice(
        order_id=order_id,
        price_usd=product.usd_price,
        description=t(lang, f"purchase.description.{product.kind.value}"),
        success_url=bot_link,
        cancel_url=bot_link,
    )
    if not invoice_url:
        return await callback.answer(t(lang, "purchase.temporarily_unavailable"), show_alert=True)

    await callback.message.edit_text(
        t(
            lang,
            f"purchase.checkout.{product.kind.value}",
            price=f"{product.usd_price:.2f}",
            normal=product.normal_credits,
            vip=product.vip_credits,
            days=product.vip_days,
        ),
        parse_mode="HTML",
        reply_markup=get_checkout_keyboard(lang, invoice_url),
    )
    await callback.answer()


@callback_router.callback_query(F.data == "profile_refresh")
async def cq_profile_refresh(callback: CallbackQuery, chat_repo: ChatRepository) -> None:
    user = await chat_repo.get_user_by_telegram_id(callback.from_user.id)
    lang = _lang(user)
    if not user:
        return await callback.answer(t("en", "errors.user_not_found"), show_alert=True)
    await callback.message.edit_text(_format_profile(user), parse_mode="HTML", reply_markup=get_profile_keyboard(user))
    await callback.answer(t(lang, "profile.refreshed"))


@callback_router.callback_query(F.data == "toggle_model")
async def cq_toggle_model(callback: CallbackQuery, chat_repo: ChatRepository, session: AsyncSession) -> None:
    user = await chat_repo.get_user_by_telegram_id(callback.from_user.id)
    lang = _lang(user)
    if not user:
        return await callback.answer(t("en", "errors.user_not_found"), show_alert=True)

    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    next_model = "PRO" if current_model == "FLASH" else "FLASH"
    if next_model == "PRO" and not user.has_active_vip:
        return await callback.answer(t(lang, "profile.model_requires_vip"), show_alert=True)

    user.preferred_text_model = next_model
    await session.commit()
    await callback.message.edit_text(_format_profile(user), parse_mode="HTML", reply_markup=get_profile_keyboard(user))
    await callback.answer(t(lang, "profile.model_switched", model=next_model))


@callback_router.callback_query(F.data == "toggle_memory")
async def cq_toggle_memory(callback: CallbackQuery, chat_repo: ChatRepository, session: AsyncSession):
    user = await chat_repo.get_user_by_telegram_id(callback.from_user.id)
    lang = _lang(user)
    if not user:
        return

    user.keep_chat_history = not user.keep_chat_history
    await session.commit()
    await callback.message.edit_text(_format_profile(user), parse_mode="HTML", reply_markup=get_profile_keyboard(user))
    await callback.answer(t(lang, "profile.memory_updated"))


@callback_router.callback_query(F.data == "claim_daily_reward")
async def cq_claim_daily_reward(callback: CallbackQuery, chat_repo: ChatRepository, session: AsyncSession):
    user = await chat_repo.get_user_by_telegram_id(callback.from_user.id)
    lang = _lang(user)
    if not user:
        return

    now = datetime.now(timezone.utc)
    if user.last_daily_reward:
        last_reward = user.last_daily_reward if user.last_daily_reward.tzinfo else user.last_daily_reward.replace(tzinfo=timezone.utc)
        if now - last_reward < timedelta(hours=24):
            remaining = timedelta(hours=24) - (now - last_reward)
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            return await callback.answer(t(lang, "wallet.daily_reward_wait", hours=hours, minutes=minutes), show_alert=True)

    billing = BillingService(session)
    await billing.add_credits(
        user_id=user.id,
        amount=12,
        entry_type=LedgerEntryType.BONUS,
        reference_type="daily_reward",
        reference_id=f"daily_reward_{user.id}_{int(now.timestamp())}",
        description="Daily reward",
        wallet_type=WalletType.NORMAL,
    )
    user.last_daily_reward = now
    await session.commit()
    await callback.message.edit_text(_format_profile(user), parse_mode="HTML", reply_markup=get_profile_keyboard(user))
    await callback.answer(t(lang, "wallet.daily_reward_added"))


@callback_router.callback_query(F.data == "cancel_action")
async def cq_cancel(callback: CallbackQuery) -> None:
    await callback.message.delete()
    await callback.answer()


@callback_router.callback_query(F.data == "redeem_promo_code")
async def cq_redeem_promo_init(callback: CallbackQuery, state: FSMContext, db_user: User | None = None):
    lang = _lang(db_user)
    await callback.message.edit_text(t(lang, "promo.enter_code"), reply_markup=get_cancel_promo_keyboard(lang), parse_mode="HTML")
    await state.set_state(PromoStates.waiting_for_code)


@callback_router.callback_query(F.data == "cancel_promo_action")
async def cq_cancel_promo(callback: CallbackQuery, state: FSMContext, db_user: User | None = None):
    lang = _lang(db_user)
    await state.clear()
    await callback.message.edit_text(t(lang, "promo.cancelled"), parse_mode="HTML", reply_markup=get_wallet_menu_keyboard(lang))


@callback_router.message(PromoStates.waiting_for_code)
async def process_promo_code(message: Message, state: FSMContext, session: AsyncSession, chat_repo: ChatRepository, db_user: User | None = None):
    lang = _lang(db_user)
    service = AdminService(session, BillingService(session))
    try:
        promo = await service.redeem_promo_code(message.from_user.id, (message.text or "").strip())
    except ValueError:
        return await message.answer(t(lang, "promo.invalid"), reply_markup=get_cancel_promo_keyboard(lang))

    user = await chat_repo.get_user_by_telegram_id(message.from_user.id)
    await state.clear()
    await message.answer(
        t(lang, "promo.redeemed", code=promo.code, normal=promo.normal_credits, vip=promo.vip_credits, days=promo.vip_days),
        parse_mode="HTML",
        reply_markup=get_profile_keyboard(user),
    )


@callback_router.callback_query(F.data == "view_chat_history")
async def view_chat_history(callback: CallbackQuery, chat_repo: ChatRepository):
    user = await chat_repo.get_user_by_telegram_id(callback.from_user.id)
    lang = _lang(user)
    if not user:
        return
    if not user.keep_chat_history:
        return await callback.answer(t(lang, "chat.history.disabled"), show_alert=True)

    conversations = await chat_repo.get_user_conversations(user.id, limit=5)
    if not conversations:
        return await callback.answer(t(lang, "chat.history.empty"), show_alert=True)

    builder = InlineKeyboardBuilder()
    for conv in conversations:
        title = t(lang, "chat.history.item", date=conv.created_at.strftime("%Y-%m-%d %H:%M"))
        builder.row(InlineKeyboardButton(text=title, callback_data=f"resume_chat_{conv.id}"))
    builder.row(InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data="profile_refresh"))

    await callback.message.edit_text(t(lang, "chat.history.title"), reply_markup=builder.as_markup(), parse_mode="HTML")


@callback_router.callback_query(F.data.startswith("resume_chat_"))
async def resume_chat(callback: CallbackQuery, chat_repo: ChatRepository, session: AsyncSession, db_user: User | None = None):
    lang = _lang(db_user)
    conv_id = int(callback.data.split("_")[2])
    await chat_repo.set_active_conversation(callback.from_user.id, conv_id)
    await session.commit()
    await callback.answer(t(lang, "chat.history.resumed"), show_alert=True)
    await callback.message.delete()
