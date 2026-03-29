from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.services.payment_service import NowPaymentsService

logger = logging.getLogger(__name__)
callback_router = Router(name="callbacks")

class PromoStates(StatesGroup):
    waiting_for_code = State()

from app.services.chat_service import ChatService

@callback_router.callback_query(F.data == "toggle_model")
async def cq_toggle_model(callback: CallbackQuery, chat_service: ChatService) -> None:
    """Toggles the user's preferred AI model and updates the profile message inline."""
    if callback.from_user is None or callback.message is None:
        return

    # 1. Fetch user from DB
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("User not found.", show_alert=True)
        return

    # 2. Toggle the model
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "PRO"
    new_model = "PRO" if current_model == "FLASH" else "FLASH"
    
    # Prevent non-VIP users from switching to PRO via the button
    if new_model == "PRO" and not user.is_vip:
        await callback.answer("👑 PRO model is for VIP members only!", show_alert=True)
        return

    user.preferred_text_model = new_model
    await chat_service._session.commit()

    # 3. Regenerate Profile Text
    plan_name = "👑 VIP Premium" if user.is_vip else "🆓 Free Tier"
    expire_text = f"\n📅 <b>Expires:</b> {user.vip_expire_date.strftime('%Y-%m-%d')}" if user.vip_expire_date else ""

    text = (
        f"👤 <b>User Profile</b>\n\n"
        f"<b>Name:</b> {user.first_name}\n"
        f"<b>ID:</b> <code>{user.telegram_id}</code>\n\n"
        f"🏷️ <b>Current Plan:</b> {plan_name}{expire_text}\n"
        f"💬 <b>Normal Credits:</b> {user.normal_credits} <i>(Free Daily)</i>\n"
        f"🪙 <b>Premium Credits:</b> {user.premium_credits} <i>(Images / Pro Chat)</i>\n\n"
        f"⚙️ <b>Preferred Text Model:</b>\n<b>{new_model}</b>"
    )

    if not user.is_vip:
        text += f"\n\n<i>Upgrade to VIP to access unlimited features!</i>"

    # 4. Edit the message inline (No new message sent!)
    from app.bot.keyboards.inline import get_profile_keyboard
    
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=get_profile_keyboard(user),
            parse_mode="HTML"
        )
    except Exception:
        pass # Ignore errors if the text is exactly the same
    
    # Show a small toast notification at the top of the user's screen
    await callback.answer(f"✅ Model switched to {new_model}!")

@callback_router.callback_query(F.data == "upgrade_vip")
async def cq_show_vip_plans_from_profile(callback: CallbackQuery) -> None:
    """Handle the upgrade_vip callback from user profile inline keyboard."""
    text = (
        "💎 <b>Choose your Premium Pack!</b>\n\n"
        "Unlock advanced features and Imagen 3 generation by purchasing Premium Credits.\n\n"
        "💳 <b>Starter:</b> 150 credits — <code>$1.99</code>\n"
        "🔥 <b>Popular:</b> 700 credits — <code>$6.99</code>\n"
        "👑 <b>Pro Pack:</b> 1800 credits — <code>$14.99</code>\n\n"
        "👇 <i>Select a plan below to pay with Crypto:</i>"
    )
    from app.bot.keyboards.inline import get_vip_plans_keyboard
    await callback.message.edit_text(text=text, reply_markup=get_vip_plans_keyboard(), parse_mode="HTML")

@callback_router.callback_query(F.data.startswith("buy_plan_"))
async def process_plan_selection(callback: CallbackQuery) -> None:
    plan_type = callback.data.split("_")[2]
    
    plans = {
        "starter": {"price": 1.99, "credits": 150, "name": "Starter Pack"},
        "popular": {"price": 6.99, "credits": 700, "name": "Popular Pack"},
        "pro": {"price": 14.99, "credits": 1800, "name": "Pro Pack"}
    }
    
    selected = plans.get(plan_type)
    if not selected:
        return await callback.answer("Error loading plan.", show_alert=True)
        
    await callback.message.edit_text("⏳ Generating your secure payment link...", parse_mode="HTML")
    
    try:
        from app.services.nowpayments_service import NowPaymentsService
        invoice_url = await NowPaymentsService.create_invoice(telegram_id=callback.from_user.id, price_usd=selected['price'])
    except Exception:
        invoice_url = None
        
    if not invoice_url:
         # Fallback generic placeholder if service fails
         invoice_url = "https://nowpayments.io/pay/"
        
    checkout_text = (
        f"🧾 <b>Invoice Generated</b>\n\n"
        f"📦 <b>Item:</b> {selected['name']}\n"
        f"💰 <b>Amount:</b> ${selected['price']}\n"
        f"🎁 <b>Reward:</b> {selected['credits']} Premium Credits\n\n"
        f"<i>Please complete your payment via NowPayments.</i>"
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    pay_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Pay ${selected['price']} in Crypto", url=invoice_url)],
        [InlineKeyboardButton(text="🔙 Back to Plans", callback_data="back_to_plans")]
    ])
    
    await callback.message.edit_text(text=checkout_text, reply_markup=pay_kb, parse_mode="HTML")

@callback_router.callback_query(F.data == "back_to_plans")
async def back_to_plans(callback: CallbackQuery) -> None:
    text = (
        "💎 <b>Choose your Premium Pack!</b>\n\n"
        "Unlock advanced features and Imagen 3 generation by purchasing Premium Credits.\n\n"
        "💳 <b>Starter:</b> 150 credits — <code>$1.99</code>\n"
        "🔥 <b>Popular:</b> 700 credits — <code>$6.99</code>\n"
        "👑 <b>Pro Pack:</b> 1800 credits — <code>$14.99</code>\n\n"
        "👇 <i>Select a plan below to pay with Crypto:</i>"
    )
    from app.bot.keyboards.inline import get_vip_plans_keyboard
    await callback.message.edit_text(text=text, reply_markup=get_vip_plans_keyboard(), parse_mode="HTML")

@callback_router.callback_query(F.data == "check_stats")
async def cq_check_stats(callback: CallbackQuery) -> None:
    """Handle the stats inline button click."""
    await callback.answer("Fetching your usage stats...", show_alert=False)
    await callback.message.answer("📊 You have used <b>0</b> out of <b>15</b> free requests today.", parse_mode="HTML")

@callback_router.callback_query(F.data == "cancel_action")
async def cq_cancel(callback: CallbackQuery) -> None:
    """Handle universal cancel."""
    await callback.message.delete()
    await callback.answer("Action canceled.")

@callback_router.callback_query(F.data == "redeem_promo_code")
async def cq_redeem_promo_init(callback: CallbackQuery, state: FSMContext):
    from app.bot.keyboards.inline import get_cancel_promo_keyboard
    text = "🎁 <b>Redeem Gift Code</b>\n\nPlease type your promo code below:"
    await callback.message.edit_text(text, reply_markup=get_cancel_promo_keyboard(), parse_mode="HTML")
    await state.set_state(PromoStates.waiting_for_code)

@callback_router.callback_query(F.data == "cancel_promo_action")
async def cq_cancel_promo(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Action cancelled. Open your profile again to see options.")

@callback_router.message(PromoStates.waiting_for_code)
async def process_promo_code(message: Message, state: FSMContext, chat_service: ChatService):
    from app.bot.keyboards.inline import get_cancel_promo_keyboard
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select, and_
    from app.db.models.user import PromoCode, UserPromo
    
    code_input = message.text.strip().upper()
    user_id = message.from_user.id
    db_session = chat_service._session
    
    # 1. Check if code exists and is valid
    promo = await db_session.scalar(select(PromoCode).where(PromoCode.code == code_input))
    
    if not promo:
        await message.answer("❌ Invalid promo code.", reply_markup=get_cancel_promo_keyboard())
        return
        
    if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
        await message.answer("⚠️ This promo code has expired.", reply_markup=get_cancel_promo_keyboard())
        await state.clear()
        return
        
    # 2. Check if user already used it
    used = await db_session.scalar(
        select(UserPromo).where(and_(UserPromo.user_id == user_id, UserPromo.promo_id == promo.id))
    )
    if used:
        await message.answer("⚠️ You have already redeemed this promo code!")
        await state.clear()
        return
        
    # 3. Apply rewards
    user = await chat_service._repo.get_user_by_telegram_id(user_id)
    user.premium_credits += promo.credits
    if promo.vip_days > 0:
        user.is_vip = True
        # Extend existing VIP or start new
        current_expire = user.vip_expire_date if user.vip_expire_date and user.vip_expire_date > datetime.now(timezone.utc) else datetime.now(timezone.utc)
        user.vip_expire_date = current_expire + timedelta(days=promo.vip_days)
        
    # Record usage
    db_session.add(UserPromo(user_id=user_id, promo_id=promo.id))
    await db_session.commit()
    
    await message.answer(
        f"🎉 <b>Success!</b>\n\n"
        f"You redeemed code <code>{promo.code}</code>\n"
        f"🎁 <b>Reward:</b> {promo.credits} Premium Credits & {promo.vip_days} Days VIP!",
        parse_mode="HTML"
    )
    await state.clear()
