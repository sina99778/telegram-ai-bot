from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.inline import get_cancel_promo_keyboard, get_profile_keyboard, get_vip_plans_keyboard
from app.core.enums import LedgerEntryType, WalletType
from app.services.admin.admin_service import AdminService
from app.services.billing.billing_service import BillingService
from app.services.chat_service import ChatService

callback_router = Router(name="callbacks")


class PromoStates(StatesGroup):
    waiting_for_code = State()


def _format_profile(user) -> str:
    vip_status = f"ACTIVE until {user.vip_expire_date:%Y-%m-%d}" if user.has_active_vip and user.vip_expire_date else (
        "ACTIVE" if user.has_active_vip else "INACTIVE"
    )
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    memory = "Keep History" if user.keep_chat_history else "Auto-Clear"
    return (
        "<b>User Profile</b>\n\n"
        f"Name: {user.first_name or user.username or 'unknown'}\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Normal credits: <code>{user.normal_credits}</code>\n"
        f"VIP credits: <code>{user.vip_credits}</code>\n"
        f"VIP access: <b>{vip_status}</b>\n"
        f"Preferred model: <b>{current_model}</b>\n"
        f"Memory: <b>{memory}</b>"
    )


@callback_router.callback_query(F.data == "toggle_model")
async def cq_toggle_model(callback: CallbackQuery, chat_service: ChatService) -> None:
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return await callback.answer("User not found.", show_alert=True)

    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    next_model = "PRO" if current_model == "FLASH" else "FLASH"
    if next_model == "PRO" and not user.has_active_vip:
        return await callback.answer("VIP access is required for Pro.", show_alert=True)

    user.preferred_text_model = next_model
    await chat_service._session.commit()
    await callback.message.edit_text(
        _format_profile(user),
        parse_mode="HTML",
        reply_markup=get_profile_keyboard(user),
    )
    await callback.answer(f"Model switched to {next_model}")


@callback_router.callback_query(F.data == "toggle_memory")
async def cq_toggle_memory(callback: CallbackQuery, chat_service: ChatService):
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return

    user.keep_chat_history = not user.keep_chat_history
    await chat_service._session.commit()
    await callback.message.edit_text(
        _format_profile(user),
        parse_mode="HTML",
        reply_markup=get_profile_keyboard(user),
    )
    await callback.answer("Memory updated")


@callback_router.callback_query(F.data == "claim_daily_reward")
async def cq_claim_daily_reward(callback: CallbackQuery, chat_service: ChatService):
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return

    now = datetime.now(timezone.utc)
    if user.last_daily_reward:
        last_reward = user.last_daily_reward if user.last_daily_reward.tzinfo else user.last_daily_reward.replace(tzinfo=timezone.utc)
        if now - last_reward < timedelta(hours=24):
            remaining = timedelta(hours=24) - (now - last_reward)
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            return await callback.answer(f"Come back in {hours}h {minutes}m", show_alert=True)

    billing = BillingService(chat_service._session)
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
    await chat_service._session.commit()
    await callback.message.edit_text(
        _format_profile(user),
        parse_mode="HTML",
        reply_markup=get_profile_keyboard(user),
    )
    await callback.answer("Daily reward added")


@callback_router.callback_query(F.data == "upgrade_vip")
async def cq_show_vip_plans_from_profile(callback: CallbackQuery) -> None:
    text = (
        "<b>Choose your Premium Pack</b>\n\n"
        "VIP access unlocks Pro, but actual Pro usage still consumes VIP credits.\n\n"
        "Starter: 150 VIP credits - <code>$1.99</code>\n"
        "Popular: 700 VIP credits - <code>$6.99</code>\n"
        "Pro Pack: 1800 VIP credits - <code>$14.99</code>"
    )
    await callback.message.edit_text(text=text, reply_markup=get_vip_plans_keyboard(), parse_mode="HTML")


@callback_router.callback_query(F.data.startswith("buy_plan_"))
async def process_plan_selection(callback: CallbackQuery):
    plan_type = callback.data.split("_")[2]
    plans = {
        "starter": {"price": 1.99, "credits": 150, "name": "Starter Pack"},
        "popular": {"price": 6.99, "credits": 700, "name": "Popular Pack"},
        "pro": {"price": 14.99, "credits": 1800, "name": "Pro Pack"},
    }
    selected = plans.get(plan_type)
    if not selected:
        return await callback.answer("Error loading plan.", show_alert=True)

    checkout_text = (
        "<b>VIP Checkout</b>\n\n"
        f"Item: {selected['name']}\n"
        f"Amount: ${selected['price']}\n"
        f"Reward: {selected['credits']} VIP credits\n\n"
        "NowPayments integration is available through the backend invoice flow."
    )
    pay_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Back to Plans", callback_data="back_to_plans")]]
    )
    await callback.message.edit_text(text=checkout_text, reply_markup=pay_kb, parse_mode="HTML")


@callback_router.callback_query(F.data == "back_to_plans")
async def back_to_plans(callback: CallbackQuery) -> None:
    await cq_show_vip_plans_from_profile(callback)


@callback_router.callback_query(F.data == "cancel_action")
async def cq_cancel(callback: CallbackQuery) -> None:
    await callback.message.delete()
    await callback.answer("Action canceled.")


@callback_router.callback_query(F.data == "redeem_promo_code")
async def cq_redeem_promo_init(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "<b>Redeem Code</b>\n\nSend your code below.",
        reply_markup=get_cancel_promo_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(PromoStates.waiting_for_code)


@callback_router.callback_query(F.data == "cancel_promo_action")
async def cq_cancel_promo(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Canceled.")


@callback_router.message(PromoStates.waiting_for_code)
async def process_promo_code(message: Message, state: FSMContext, chat_service: ChatService):
    service = AdminService(chat_service._session, BillingService(chat_service._session))
    try:
        promo = await service.redeem_promo_code(message.from_user.id, (message.text or "").strip())
    except ValueError as exc:
        return await message.answer(str(exc), reply_markup=get_cancel_promo_keyboard())

    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)
    await state.clear()
    await message.answer(
        "<b>Code Redeemed</b>\n\n"
        f"Code: <code>{promo.code}</code>\n"
        f"Normal credits: <code>{promo.normal_credits}</code>\n"
        f"VIP credits: <code>{promo.vip_credits}</code>\n"
        f"VIP days: <code>{promo.vip_days}</code>",
        parse_mode="HTML",
        reply_markup=get_profile_keyboard(user),
    )


@callback_router.callback_query(F.data == "view_chat_history")
async def view_chat_history(callback: CallbackQuery, chat_service: ChatService):
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    if not user.keep_chat_history:
        return await callback.answer("Memory is OFF.", show_alert=True)

    conversations = await chat_service._repo.get_user_conversations(user.id, limit=5)
    if not conversations:
        return await callback.answer("No saved chats found yet.", show_alert=True)

    builder = InlineKeyboardBuilder()
    for conv in conversations:
        title = f"Chat {conv.created_at.strftime('%Y-%m-%d %H:%M')}"
        builder.row(InlineKeyboardButton(text=title, callback_data=f"resume_chat_{conv.id}"))
    builder.row(InlineKeyboardButton(text="Back to Profile", callback_data="cancel_action"))

    await callback.message.edit_text(
        "<b>Your Saved Conversations</b>\n\nSelect a chat below to resume it.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@callback_router.callback_query(F.data.startswith("resume_chat_"))
async def resume_chat(callback: CallbackQuery, chat_service: ChatService):
    conv_id = int(callback.data.split("_")[2])
    await chat_service._repo.set_active_conversation(callback.from_user.id, conv_id)
    await chat_service._session.commit()
    await callback.answer("Conversation resumed", show_alert=True)
    await callback.message.delete()
