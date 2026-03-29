from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery

from app.bot.keyboards.inline import get_profile_keyboard
from app.services.chat_service import ChatService

menu_router = Router(name="menu")

@menu_router.message(F.text == "🎁 Invite Friends")
async def menu_invite(message: Message) -> None:
    """Generate and send the user's referral link."""
    if message.from_user is None:
        return
        
    bot_info = await message.bot.me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"
    
    text = (
        "🎁 <b>Invite Friends & Earn Credits!</b>\n\n"
        "Share your unique link with friends. Every time a new user starts the bot using your link, "
        "you will instantly receive <b>+10 Premium Credits</b> for Gemini 3.1 Pro & Nano Banana 2!\n\n"
        f"🔗 <b>Your Link:</b>\n<code>{ref_link}</code>"
    )
    await message.answer(text, parse_mode="HTML")

@menu_router.message(F.text == "👤 My Profile")
async def menu_profile(message: Message, chat_service: ChatService) -> None:
    if message.from_user is None: return
        
    user = await chat_service._repo.ensure_daily_credits(message.from_user.id)
    if not user: return # Should not happen

    plan_name = "👑 VIP Premium" if user.is_vip else "🆓 Free Tier"
    
    text = (
        f"👤 <b>User Profile</b>\n\n"
        f"Name: {user.first_name}\n\n"
        f"🏷️ Current Plan: {plan_name}\n"
        f"💬 Normal Credits: {user.normal_credits} <i>(Free Daily)</i>\n"
        f"🪙 Premium Credits: {user.premium_credits} <i>(Images / Pro Chat)</i>\n\n"
        f"⚙️ Preferred Text Model:\n<b>{user.preferred_text_model.upper()}</b>"
    )
    
    # Pass user vip status and preferred model to get dynamic keyboard
    await message.answer(text, reply_markup=get_profile_keyboard(user.is_vip, user.preferred_text_model), parse_mode="HTML")

# Handle the model switch callback
@menu_router.callback_query(F.data == "switch_text_model")
async def callback_switch_model(callback: CallbackQuery, chat_service: ChatService) -> None:
    """Toggles user's preferred model between Flash and Pro."""
    user = await chat_service._repo.get_user_by_telegram_id(callback.from_user.id)
    if not user: return

    # Toggle logic
    new_model = 'pro' if user.preferred_text_model == 'flash' else 'flash'
    user.preferred_text_model = new_model
    await chat_service._session.commit()
    
    text = f"✅ Your preferred text model is now set to <b>{new_model.upper()}</b>."
    
    # Answer callback so it doesn't spin
    await callback.answer(text, show_alert=True)
    
    # Optionally, update the message to reflect the change visually
    await callback.message.edit_reply_markup(reply_markup=get_profile_keyboard(user.is_vip, new_model))

@menu_router.message(F.text == "👑 VIP Premium")
async def menu_vip(message: Message) -> None:
    """Handle the VIP button."""
    text = (
        "👑 <b>VIP Premium Features</b>\n\n"
        "Unlock the full power of the AI Hub:\n"
        "✨ <b>Gemini 3.1 Pro:</b> Advanced reasoning and coding.\n"
        "🎨 <b>Nano Banana 2:</b> State-of-the-art Image Generation.\n"
        "🎙️ <b>Voice AI:</b> Native audio processing.\n"
        "⚡ <b>Unlimited Context:</b> Never lose your chat history.\n\n"
        "<i>Click the button below to upgrade your account!</i>"
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Purchase VIP", callback_data="upgrade_vip")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@menu_router.message(F.text == "📞 Support")
async def menu_support(message: Message) -> None:
    """Handle the Support button."""
    text = (
        "📞 <b>Support Team</b>\n\n"
        "If you have any questions, face any issues, or want to purchase a VIP subscription via direct transfer, "
        "please contact our admin:\n\n"
        "👉 <b>@ThereIsStillSina</b>"
    )
    await message.answer(text, parse_mode="HTML")

@menu_router.message(F.text.in_({"💬 Chat with AI", "🖼️ Generate Image", "🎙️ Voice Assistant"}))
async def menu_tools(message: Message, chat_service: ChatService) -> None:
    """Handle tool selection buttons."""
    if message.from_user is None:
        return

    # Fetch user from DB to check credits
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)

    if message.text == "💬 Chat with AI":
        await message.answer("Just type any message below and I will reply using Gemini!")
        
    elif message.text == "🖼️ Generate Image":
        if user and (user.is_vip or user.premium_credits >= 15):
            await message.answer("🎨 <b>Nano Banana 2 is Ready!</b>\n\nTo generate an image, use the command like this:\n<code>/image A futuristic city at night</code>", parse_mode="HTML")
        else:
            await message.answer("🎨 <b>Image Generation</b> requires VIP or at least 15 Premium Credits. Please upgrade your plan.", parse_mode="HTML")
            
    elif message.text == "🎙️ Voice Assistant":
        await message.answer("🎙️ <b>Voice Processing</b> is coming in the next update!", parse_mode="HTML")
