from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards.inline import get_profile_keyboard
from app.services.chat_service import ChatService

menu_router = Router(name="menu")

@menu_router.message(F.text == "👤 My Profile")
async def menu_profile(message: Message, chat_service: ChatService) -> None:
    """Handle the Profile button and show real DB stats."""
    if message.from_user is None:
        return
        
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("User profile not found. Please type /start first.")
        return

    plan_name = "👑 VIP Premium" if user.is_vip else "🆓 Free Tier"
    expire_text = f"\n📅 <b>Expires:</b> {user.vip_expire_date.strftime('%Y-%m-%d')}" if user.vip_expire_date else ""

    text = (
        f"👤 <b>User Profile</b>\n\n"
        f"<b>Name:</b> {user.first_name}\n"
        f"<b>ID:</b> <code>{user.telegram_id}</code>\n\n"
        f"🏷️ <b>Current Plan:</b> {plan_name}{expire_text}\n"
        f"🪙 <b>Image Credits:</b> {user.image_credits}\n\n"
    )
    
    if not user.is_vip:
        text += f"<i>Upgrade to VIP to access Gemini 3.1 Pro and Nano Banana 2!</i>"

    await message.answer(text, reply_markup=get_profile_keyboard(), parse_mode="HTML")

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
async def menu_tools(message: Message) -> None:
    """Handle tool selection buttons."""
    if message.text == "💬 Chat with AI":
        await message.answer("Just type any message below and I will reply using Gemini!")
    elif message.text == "🖼️ Generate Image":
        await message.answer("🎨 <b>Image Generation</b> (Nano Banana 2) is a VIP feature. Please upgrade your plan to generate images.", parse_mode="HTML")
    elif message.text == "🎙️ Voice Assistant":
        await message.answer("🎙️ <b>Voice Processing</b> is a VIP feature. Please upgrade your plan to send voice notes.", parse_mode="HTML")
