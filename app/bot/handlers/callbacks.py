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

@callback_router.callback_query(F.data == "toggle_memory")
async def cq_toggle_memory(callback: CallbackQuery, chat_service: ChatService):
    if callback.from_user is None: return
    
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user: return
    
    user.keep_chat_history = not user.keep_chat_history
    await chat_service._session.commit()
    
    # Custom alert message
    if user.keep_chat_history:
        if user.is_vip:
            alert_msg = "✅ Memory ON! I will remember our entire conversation."
        else:
            alert_msg = "✅ Memory ON! (Free limit: I will only remember our last 2 chats. Upgrade to VIP for unlimited memory!)"
    else:
        alert_msg = "🧹 Memory OFF! Chats will auto-clear after 2 hours."
        
    await callback.answer(alert_msg, show_alert=True)
    
    # Regenerate Profile Text 
    plan_name = "👑 VIP Premium" if user.is_vip else "🆓 Free Tier"
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "PRO"
    mem_status = "Keep History" if user.keep_chat_history else "Auto-Clear"
    
    text = (
        f"👤 <b>User Profile</b>\n\n"
        f"<b>Name:</b> {user.first_name}\n"
        f"<b>ID:</b> <code>{user.telegram_id}</code>\n\n"
        f"🏷️ <b>Current Plan:</b> {plan_name}\n"
        f"💬 <b>Normal Credits:</b> {user.normal_credits}\n"
        f"🪙 <b>Premium Credits:</b> {user.premium_credits}\n\n"
        f"⚙️ <b>Model:</b> {current_model}\n"
        f"🧠 <b>Memory:</b> {mem_status}"
    )
    
@callback_router.callback_query(F.data == "claim_daily_reward")
async def cq_claim_daily_reward(callback: CallbackQuery, chat_service: ChatService):
    from datetime import datetime, timezone, timedelta
    
    if callback.from_user is None: return
    
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user: return
    
    now = datetime.now(timezone.utc)
    
    # Check if 24 hours have passed
    if user.last_daily_reward:
        last_reward = user.last_daily_reward
        if last_reward.tzinfo is None:
            last_reward = last_reward.replace(tzinfo=timezone.utc)
            
        time_since_last = now - last_reward
        if time_since_last < timedelta(hours=24):
            # Calculate remaining time
            remaining = timedelta(hours=24) - time_since_last
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            
            alert_msg = f"⏳ Not ready yet!\n\nPlease come back in {hours} hours and {minutes} minutes to claim your next reward."
            if user.language == "fa":
                alert_msg = f"⏳ هنوز آماده نیست!\n\nلطفاً {hours} ساعت و {minutes} دقیقه دیگر برای دریافت جایزه برگردید."
                
            return await callback.answer(alert_msg, show_alert=True)
            
    # Grant Reward: 2 Premium Credits + 10 Normal Credits
    user.premium_credits += 2
    user.normal_credits += 10
    user.last_daily_reward = now
    await chat_service._session.commit()
    
    success_msg = "🎉 Congratulations! You received 2 Premium Credits and 10 Normal Credits!"
    if user.language == "fa":
        success_msg = "🎉 تبریک! ۲ سکه پریمیوم و ۱۰ سکه عادی به حساب شما اضافه شد!"
        
    await callback.answer(success_msg, show_alert=True)
    
    # Regenerate Profile Text to show new balance
    plan_name = "👑 VIP Premium" if user.is_vip else "🆓 Free Tier"
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "PRO"
    mem_status = "Keep History" if user.keep_chat_history else "Auto-Clear"
    
    if user.language == "fa":
        text = (
            f"👤 <b>پروفایل کاربری</b>\n\n"
            f"<b>نام:</b> {user.first_name}\n"
            f"<b>آیدی:</b> <code>{user.telegram_id}</code>\n\n"
            f"🏷️ <b>طرح فعلی:</b> {plan_name}\n"
            f"💬 <b>سکه‌های عادی:</b> {user.normal_credits}\n"
            f"🪙 <b>سکه‌های پریمیوم:</b> {user.premium_credits}\n\n"
            f"⚙️ <b>مدل هوش مصنوعی:</b> {current_model}\n"
            f"🧠 <b>وضعیت حافظه:</b> {mem_status}"
        )
    else:
        text = (
            f"👤 <b>User Profile</b>\n\n"
            f"<b>Name:</b> {user.first_name}\n"
            f"<b>ID:</b> <code>{user.telegram_id}</code>\n\n"
            f"🏷️ <b>Current Plan:</b> {plan_name}\n"
            f"💬 <b>Normal Credits:</b> {user.normal_credits}\n"
            f"🪙 <b>Premium Credits:</b> {user.premium_credits}\n\n"
            f"⚙️ <b>Model:</b> {current_model}\n"
            f"🧠 <b>Memory:</b> {mem_status}"
        )
    
    from app.bot.keyboards.inline import get_profile_keyboard
    try:
        await callback.message.edit_text(text=text, reply_markup=get_profile_keyboard(user), parse_mode="HTML")
    except Exception:
        pass

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

import os
import time
import aiohttp

async def create_nowpayments_invoice(price: float, plan_name: str, user_id: int) -> str:
    """Calls NowPayments API to generate a dynamic invoice link."""
    api_key = os.environ.get("NOWPAYMENTS_API_KEY")
    fallback_url = "https://nowpayments.io"
    
    if not api_key:
        return fallback_url

    url = "https://api.nowpayments.io/v1/invoice"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    # Create a unique order ID for tracking
    order_id = f"VIP_{user_id}_{int(time.time())}"
    
    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": f"Premium Credits: {plan_name}",
        # Change this to your actual bot's t.me link
        "success_url": "https://t.me/YOUR_BOT_USERNAME", 
        "cancel_url": "https://t.me/YOUR_BOT_USERNAME"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("invoice_url", fallback_url)
                else:
                    return fallback_url
    except Exception:
        return fallback_url


@callback_router.callback_query(F.data.startswith("buy_plan_"))
async def process_plan_selection(callback: CallbackQuery):
    plan_type = callback.data.split("_")[2]
    
    plans = {
        "starter": {"price": 1.99, "credits": 150, "name": "Starter Pack"},
        "popular": {"price": 6.99, "credits": 700, "name": "Popular Pack"},
        "pro": {"price": 14.99, "credits": 1800, "name": "Pro Pack"}
    }
    
    selected = plans.get(plan_type)
    if not selected:
        return await callback.answer("Error loading plan.", show_alert=True)
        
    # Show a loading message while API is fetching the link
    await callback.message.edit_text("⏳ <i>Generating secure payment link...</i>", parse_mode="HTML")
    
    # Call the API dynamically
    payment_url = await create_nowpayments_invoice(
        price=selected['price'], 
        plan_name=selected['name'], 
        user_id=callback.from_user.id
    )
    
    checkout_text = (
        f"🧾 <b>Invoice Generated</b>\n\n"
        f"📦 <b>Item:</b> {selected['name']}\n"
        f"💰 <b>Amount:</b> ${selected['price']}\n"
        f"🎁 <b>Reward:</b> {selected['credits']} Premium Credits\n\n"
        f"<i>Please complete your payment via NowPayments.</i>"
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    pay_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Pay ${selected['price']} in Crypto", url=payment_url)],
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
    from app.db.models import PromoCode, UserPromo
    from app.services.billing.billing_service import BillingService
    from app.core.enums import LedgerEntryType
    
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
    
    if promo.credits > 0:
        # Use new BillingService to safely add credits and keep ledger
        billing = BillingService(db_session)
        await billing.add_credits(
            user_id=user.id,
            amount=promo.credits,
            entry_type=LedgerEntryType.BONUS, # Or appropriate enum
            reference_type="promo_code",
            reference_id=f"promo_{promo.id}_user_{user.id}",
            description=f"Redeemed promo code: {promo.code}"
        )
        
    # Also add to legacy premium_credits if system relies on both currently
    user.premium_credits += promo.credits
        
    if promo.vip_days > 0:
        user.is_vip = True
        # Extend existing VIP or start new
        current_expire = user.vip_expire_date if user.vip_expire_date and user.vip_expire_date > datetime.now(timezone.utc) else datetime.now(timezone.utc)
        user.vip_expire_date = current_expire + timedelta(days=promo.vip_days)
        
    # Record usage
    db_session.add(UserPromo(user_id=user.id, promo_id=promo.id))
    
    await db_session.commit()
    
    await message.answer(
        f"🎉 <b>Success!</b>\n\n"
        f"You redeemed code <code>{promo.code}</code>\n"
        f"🎁 <b>Reward:</b> {promo.credits} Credits & {promo.vip_days} Days VIP!",
        parse_mode="HTML"
    )
    await state.clear()

from aiogram.utils.keyboard import InlineKeyboardBuilder

@callback_router.callback_query(F.data == "view_chat_history")
async def view_chat_history(callback: CallbackQuery, chat_service: ChatService):
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user: return
    
    # Check if they have memory enabled
    if not user.keep_chat_history:
        return await callback.answer("⚠️ Memory is OFF. Turn it ON in your profile to save chats.", show_alert=True)

    conversations = await chat_service._repo.get_user_conversations(user.id, limit=5)
    if not conversations:
        return await callback.answer("No saved chats found yet.", show_alert=True)

    builder = InlineKeyboardBuilder()
    for conv in conversations:
        # Create a button for each conversation (using its creation date as title)
        title = f"💬 Chat: {conv.created_at.strftime('%Y-%m-%d %H:%M')}"
        builder.row(InlineKeyboardButton(text=title, callback_data=f"resume_chat_{conv.id}"))

    # Add back button to profile
    builder.row(InlineKeyboardButton(text="🔙 Back to Profile", callback_data="cancel_action"))

    await callback.message.edit_text(
        "📂 <b>Your Saved Conversations:</b>\n\nSelect a chat below to resume it:", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )

@callback_router.callback_query(F.data.startswith("resume_chat_"))
async def resume_chat(callback: CallbackQuery, chat_service: ChatService):
    conv_id = int(callback.data.split("_")[2])
    
    # Tell the DB to make this conversation the active one
    await chat_service._repo.set_active_conversation(callback.from_user.id, conv_id)
    await chat_service._session.commit()
    
    await callback.answer("✅ Conversation resumed! Send a message to continue.", show_alert=True)
    # Optionally delete the inline menu to clean up the chat
    await callback.message.delete()
