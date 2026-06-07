from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    get_cancel_keyboard,
    get_cancel_promo_keyboard,
    get_checkout_keyboard,
    get_normal_credit_packs_keyboard,
    get_payment_method_keyboard,
    get_profile_keyboard,
    get_support_menu_keyboard,
    get_vip_access_packs_keyboard,
    get_vip_credit_packs_keyboard,
    get_vip_menu_keyboard,
    get_wallet_menu_keyboard,
)
from app.core.config import settings
from app.core.enums import LedgerEntryType, TransactionStatus, WalletType
from app.core.i18n import t
from app.db.models import PaymentTransaction, User
from app.db.repositories.chat_repo import ChatRepository
from app.services.admin.admin_service import AdminService
from app.services.billing.billing_service import BillingService
from app.services.config.runtime_config import RuntimeConfig
from app.services.payment_service import NowPaymentsService
from app.services.purchase.catalog import build_card_idempotency_key, build_order_id, get_product

callback_router = Router(name="callbacks")


class PromoStates(StatesGroup):
    waiting_for_code = State()


class CardPayStates(StatesGroup):
    waiting_for_receipt = State()


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


def _format_profile(user: User) -> str:
    lang = _lang(user)
    vip_until = user.active_vip_until
    vip_status = (
        t(lang, "profile.vip.active_until", date=vip_until.strftime("%Y-%m-%d"))
        if user.has_active_vip and vip_until
        else (t(lang, "profile.vip.active") if user.has_active_vip else t(lang, "profile.vip.inactive"))
    )
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    memory = t(lang, "profile.memory.keep") if user.keep_chat_history else t(lang, "profile.memory.clear")
    billing = t(lang, "profile.billing.payg") if getattr(user, "payg_enabled", False) else t(lang, "profile.billing.flat")
    return "\n".join(
        [
            t(lang, "profile.title"),
            "",
            t(lang, "profile.name", value=html.escape(user.first_name or user.username or "unknown")),
            t(lang, "profile.id", value=user.telegram_id),
            t(lang, "profile.normal_credits", value=user.normal_credits),
            t(lang, "profile.vip_credits", value=user.vip_credits),
            t(lang, "profile.vip_status", value=vip_status),
            t(lang, "profile.model", value=current_model),
            t(lang, "profile.memory", value=memory),
            t(lang, "profile.billing", value=billing),
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


def _pack_label(lang: str, code: str) -> str:
    label = t(lang, f"packs.{code}")
    return label if label != f"packs.{code}" else code


@callback_router.callback_query(F.data.startswith("purchase:"))
async def cb_purchase_checkout(callback: CallbackQuery, db_user: User | None = None):
    """Step 1: a pack was chosen — let the user pick a payment method."""
    lang = _lang(db_user)
    code = callback.data.split(":", 1)[1]
    product = get_product(code)
    if not product:
        return await callback.answer(t(lang, "purchase.not_found"), show_alert=True)

    await callback.message.edit_text(
        t(lang, "purchase.method_choose", pack=_pack_label(lang, code), price=f"{product.usd_price:.2f}"),
        parse_mode="HTML",
        reply_markup=get_payment_method_keyboard(lang, code),
    )
    await callback.answer()


@callback_router.callback_query(F.data.startswith("pay:crypto:"))
async def cb_pay_crypto(callback: CallbackQuery, db_user: User | None = None):
    """Crypto path — create a NowPayments invoice (unchanged behaviour)."""
    lang = _lang(db_user)
    code = callback.data.split(":", 2)[2]
    product = get_product(code)
    if not product:
        return await callback.answer(t(lang, "purchase.not_found"), show_alert=True)

    bot_info = await callback.bot.get_me()
    bot_link = f"https://t.me/{bot_info.username}" if bot_info.username else "https://t.me"
    order_id = build_order_id(code, callback.from_user.id, int(datetime.now(timezone.utc).timestamp()))
    try:
        invoice_url = await NowPaymentsService.create_invoice(
            order_id=order_id,
            price_usd=product.usd_price,
            description=t(lang, f"purchase.description.{product.kind.value}"),
            success_url=bot_link,
            cancel_url=bot_link,
        )
    except Exception:
        invoice_url = None
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


@callback_router.callback_query(F.data.startswith("pay:card:"))
async def cb_pay_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext, db_user: User | None = None):
    """Card-to-card path — show the destination card and await a receipt photo."""
    lang = _lang(db_user)
    code = callback.data.split(":", 2)[2]
    product = get_product(code)
    if not product:
        return await callback.answer(t(lang, "purchase.not_found"), show_alert=True)

    card_number = await RuntimeConfig.get_text(session, "card_number")
    if not card_number.strip():
        return await callback.answer(t(lang, "purchase.card.not_configured"), show_alert=True)
    card_holder = await RuntimeConfig.get_text(session, "card_holder")
    card_note = await RuntimeConfig.get_text(session, "card_note")

    # USD→Toman conversion for the displayed amount (rate is admin-set; 0 hides it).
    rate = await RuntimeConfig.get_int(session, "usd_toman_rate")
    if rate > 0:
        toman = int(round(product.usd_price * rate))
        toman_line = t(lang, "purchase.card.toman_line", toman=f"{toman:,}")
    else:
        toman_line = ""

    await state.set_state(CardPayStates.waiting_for_receipt)
    await state.update_data(card_product=code)
    await callback.message.edit_text(
        t(
            lang,
            "purchase.card.instructions",
            pack=_pack_label(lang, code),
            price=f"{product.usd_price:.2f}",
            toman_line=toman_line,
            card_number=card_number,
            card_holder=card_holder or "-",
            note=card_note,
        ),
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard(lang),
    )
    await callback.answer()


@callback_router.message(CardPayStates.waiting_for_receipt)
async def process_card_receipt(message: Message, state: FSMContext, session: AsyncSession, db_user: User | None = None):
    """Step 2: user uploads the receipt photo → create a PENDING transaction."""
    lang = _lang(db_user)
    if not message.photo:
        return await message.answer(t(lang, "purchase.card.not_a_photo"), parse_mode="HTML")

    data = await state.get_data()
    code = data.get("card_product")
    product = get_product(code) if code else None
    if not product or not db_user:
        await state.clear()
        return await message.answer(t(lang, "purchase.not_found"), parse_mode="HTML")

    receipt_file_id = message.photo[-1].file_id
    tx = PaymentTransaction(
        user_id=db_user.id,
        provider="card_to_card",
        provider_payment_id=receipt_file_id,
        amount=product.usd_price,
        currency="USD",
        credits_granted=0,
        status=TransactionStatus.PENDING,
        idempotency_key=build_card_idempotency_key(db_user.telegram_id, message.message_id),
        raw_payload={
            "product_code": code,
            "receipt_file_id": receipt_file_id,
            "telegram_id": db_user.telegram_id,
        },
    )
    session.add(tx)
    await session.commit()
    await session.refresh(tx)
    await state.clear()

    await message.answer(
        t(lang, "purchase.card.receipt_received", pack=_pack_label(lang, code)),
        parse_mode="HTML",
        reply_markup=get_wallet_menu_keyboard(lang),
    )

    # Notify configured admins (best-effort; never blocks the user).
    for admin_id in settings.admin_ids_list:
        try:
            await message.bot.send_message(
                chat_id=admin_id,
                text=t(
                    "fa",
                    "admin.cardpay.notify",
                    telegram_id=db_user.telegram_id,
                    pack=_pack_label("fa", code),
                    price=f"{product.usd_price:.2f}",
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


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


@callback_router.callback_query(F.data == "toggle_payg")
async def cq_toggle_payg(callback: CallbackQuery, chat_repo: ChatRepository, session: AsyncSession):
    user = await chat_repo.get_user_by_telegram_id(callback.from_user.id)
    lang = _lang(user)
    if not user:
        return await callback.answer(t("en", "errors.user_not_found"), show_alert=True)

    user.payg_enabled = not user.payg_enabled
    await session.commit()
    await callback.message.edit_text(_format_profile(user), parse_mode="HTML", reply_markup=get_profile_keyboard(user))
    await callback.answer(t(lang, "profile.payg_switched"))


@callback_router.callback_query(F.data == "toggle_memory")
async def cq_toggle_memory(callback: CallbackQuery, chat_repo: ChatRepository, session: AsyncSession):
    user = await chat_repo.get_user_by_telegram_id(callback.from_user.id)
    lang = _lang(user)
    if not user:
        return await callback.answer(t("en", "errors.user_not_found"), show_alert=True)

    user.keep_chat_history = not user.keep_chat_history
    await session.commit()
    await callback.message.edit_text(_format_profile(user), parse_mode="HTML", reply_markup=get_profile_keyboard(user))
    await callback.answer(t(lang, "profile.memory_updated"))


@callback_router.callback_query(F.data == "claim_daily_reward")
async def cq_claim_daily_reward(callback: CallbackQuery, chat_repo: ChatRepository, session: AsyncSession):
    user = await chat_repo.get_user_by_telegram_id(callback.from_user.id)
    lang = _lang(user)
    if not user:
        return await callback.answer(t("en", "errors.user_not_found"), show_alert=True)

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
    await callback.answer()


@callback_router.callback_query(F.data == "cancel_promo_action")
async def cq_cancel_promo(callback: CallbackQuery, state: FSMContext, db_user: User | None = None):
    lang = _lang(db_user)
    await state.clear()
    await callback.message.edit_text(t(lang, "promo.cancelled"), parse_mode="HTML", reply_markup=get_wallet_menu_keyboard(lang))
    await callback.answer()


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
        return await callback.answer(t("en", "errors.user_not_found"), show_alert=True)
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
    await callback.answer()


@callback_router.callback_query(F.data.startswith("resume_chat_"))
async def resume_chat(callback: CallbackQuery, chat_repo: ChatRepository, session: AsyncSession, db_user: User | None = None):
    lang = _lang(db_user)
    # callback_data is "resume_chat_<id>"; guard against malformed data so a
    # bad/old button can't crash the handler before we acknowledge it.
    parts = (callback.data or "").split("_")
    if len(parts) < 3 or not parts[2].isdigit():
        return await callback.answer()
    conv_id = int(parts[2])
    await chat_repo.set_active_conversation(callback.from_user.id, conv_id)
    await session.commit()
    await callback.answer(t(lang, "chat.history.resumed"), show_alert=True)
    await callback.message.delete()
