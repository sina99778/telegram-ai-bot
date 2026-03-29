from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery

from app.bot.keyboards.inline import get_profile_keyboard
from app.bot.keyboards.reply import get_main_menu
from app.services.chat_service import ChatService
from app.core.i18n import t, TEXTS

menu_router = Router(name="menu")

PROFILE_BTNS = {TEXTS["en"]["btn_profile"], TEXTS["fa"]["btn_profile"]}
INVITE_BTNS = {TEXTS["en"]["btn_invite"], TEXTS["fa"]["btn_invite"]}
VIP_BTNS = {TEXTS["en"]["btn_vip"], TEXTS["fa"]["btn_vip"]}
SUPPORT_BTNS = {TEXTS["en"]["btn_support"], TEXTS["fa"]["btn_support"]}
TOOLS_BTNS = {
    TEXTS["en"]["btn_chat"], TEXTS["fa"]["btn_chat"],
    TEXTS["en"]["btn_image"], TEXTS["fa"]["btn_image"]
}

@menu_router.message(F.text.in_({TEXTS["en"]["btn_lang"], TEXTS["fa"]["btn_lang"]}))
async def toggle_lang(message: Message, chat_service: ChatService) -> None:
    if message.from_user is None:
        return
        
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
        
    new_lang = "en" if user.language == "fa" else "fa"
    user.language = new_lang
    await chat_service._session.commit()
    await message.answer(t("lang_changed", new_lang), reply_markup=get_main_menu(new_lang))

@menu_router.message(F.text.in_(INVITE_BTNS))
async def menu_invite(message: Message, chat_service: ChatService) -> None:
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)
    bot_info = await message.bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start=ref_{user.telegram_id}" if user else ""
    lang = user.language if user else "fa"
    
    if lang == "fa":
        text = (
            "🎁 <b>دعوت از دوستان و دریافت جایزه!</b>\n\n"
            f"👥 <b>تعداد دعوت‌های شما:</b> {user.total_invites if user else 0} نفر\n"
            f"🖼 <b>تصاویر هدیه باقیمانده:</b> {user.special_reward_images_left if user else 0} عکس\n\n"
            "با هر دعوت <b>۱۰ سکه پریمیوم</b> بگیرید. با رسیدن به ۱۰ دعوت، قابلیت <b>۵ عکس با کیفیت بالا (Imagen 3)</b> به مدت یک هفته برایتان فعال می‌شود!\n\n"
            f"🔗 <b>لینک اختصاصی شما:</b>\n<code>{invite_link}</code>"
        )
    else:
        text = (
            "🎁 <b>Invite Friends & Earn!</b>\n\n"
            f"👥 <b>Total Invites:</b> {user.total_invites if user else 0}\n"
            f"🖼 <b>Reward Images Left:</b> {user.special_reward_images_left if user else 0}\n\n"
            "Earn <b>10 Premium Credits</b> per invite. Reach 10 invites to unlock <b>5 High-Res Images (Imagen 3)</b> for 1 week!\n\n"
            f"🔗 <b>Your Link:</b>\n<code>{invite_link}</code>"
        )
    await message.answer(text, parse_mode="HTML")



@menu_router.message(F.text.in_(PROFILE_BTNS))
async def menu_profile(message: Message, chat_service: ChatService) -> None:
    if message.from_user is None: return
    
    user = await chat_service._repo.ensure_daily_credits(message.from_user.id)
    if not user: return # Should not happen
    
    lang = user.language if user else "fa"

    plan_name = "👑 VIP Premium" if user.is_vip else "🆓 Free Tier"
    
    text = (
        f"👤 <b>User Profile</b>\n\n"
        f"<b>Name:</b> {user.first_name}\n"
        f"<b>ID:</b> <code>{user.telegram_id}</code>\n\n"
        f"🏷️ <b>Current Plan:</b> {plan_name}\n"
        f"💬 <b>Normal Credits:</b> {user.normal_credits} <i>(Free Daily)</i>\n"
        f"🪙 <b>Premium Credits:</b> {user.premium_credits} <i>(Images / Pro Chat)</i>\n\n"
        f"⚙️ <b>Preferred Text Model:</b>\n<b>{str(user.preferred_text_model).upper() if user.preferred_text_model else 'PRO'}</b>"
    )

    if not user.is_vip:
        text += f"\n\n<i>Upgrade to VIP to access unlimited features!</i>"
    
    # Pass user object to get dynamic keyboard
    await message.answer(text, reply_markup=get_profile_keyboard(user), parse_mode="HTML")

@menu_router.message(F.text.in_(VIP_BTNS))
async def show_vip_plans(message: Message, chat_service: ChatService) -> None:
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)
    lang = user.language if user else "fa"
    
    if lang == "fa":
        text = (
            "💎 <b>بسته ویژه خود را انتخاب کنید!</b>\n\n"
            "با خرید سکه پریمیوم، محدودیت‌ها را بردارید و از تصویرساز Imagen 3 استفاده کنید.\n\n"
            "💳 <b>شروع:</b> ۱۵۰ سکه — <code>۱.۹۹ دلار</code>\n"
            "🔥 <b>محبوب:</b> ۷۰۰ سکه — <code>۶.۹۹ دلار</code>\n"
            "👑 <b>حرفه‌ای:</b> ۱۸۰۰ سکه — <code>۱۴.۹۹ دلار</code>\n\n"
            "👇 <i>برای پرداخت کریپتویی یک پلن را انتخاب کنید:</i>"
        )
    else:
        text = (
            "💎 <b>Choose your Premium Pack!</b>\n\n"
            "Unlock advanced features and Imagen 3 generation by purchasing Premium Credits.\n\n"
            "💳 <b>Starter:</b> 150 credits — <code>$1.99</code>\n"
            "🔥 <b>Popular:</b> 700 credits — <code>$6.99</code>\n"
            "👑 <b>Pro Pack:</b> 1800 credits — <code>$14.99</code>\n\n"
            "👇 <i>Select a plan below to pay with Crypto:</i>"
        )
    from app.bot.keyboards.inline import get_vip_plans_keyboard
    await message.answer(text, reply_markup=get_vip_plans_keyboard(), parse_mode="HTML")

@menu_router.message(F.text.in_(SUPPORT_BTNS))
async def menu_support(message: Message) -> None:
    """Handle the Support button."""
    text = (
        "📞 <b>Support Team</b>\n\n"
        "If you have any questions, face any issues, or want to purchase a VIP subscription via direct transfer, "
        "please contact our admin:\n\n"
        "👉 <b>@ThereIsStillSina</b>"
    )
    await message.answer(text, parse_mode="HTML")

@menu_router.message(F.text.in_(TOOLS_BTNS))
async def menu_tools(message: Message, chat_service: ChatService) -> None:
    """Handle tool selection buttons."""
    if message.from_user is None:
        return

    # Fetch user from DB to check credits
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)

    if message.text in {TEXTS["en"]["btn_chat"], TEXTS["fa"]["btn_chat"]}:
        await message.answer("Just type any message below and I will reply using Gemini!")
        
    elif message.text in {TEXTS["en"]["btn_image"], TEXTS["fa"]["btn_image"]}:
        if user and (user.is_vip or user.premium_credits >= 10):
            await message.answer("🎨 <b>Imagen 3 is Ready!</b>\n\nTo generate an image, use the command like this:\n<code>/image A futuristic city at night</code>", parse_mode="HTML")
        else:
            await message.answer("🎨 <b>Image Generation</b> requires VIP or at least 15 Premium Credits. Please upgrade your plan.", parse_mode="HTML")
