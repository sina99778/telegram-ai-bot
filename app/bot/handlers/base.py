from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message, URLInputFile

from app.bot.keyboards.reply import get_main_menu
from app.core.access import is_configured_admin
from app.services.chat_service import ChatService

base_router = Router(name="base")


@base_router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, chat_service: ChatService) -> None:
    if message.from_user is None:
        return

    await chat_service._repo.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    payload = command.args
    if payload and payload.startswith("ref_"):
        try:
            referrer_tg_id = int(payload.split("_")[1])
            await chat_service._repo.process_referral(message.from_user.id, referrer_tg_id)
        except ValueError:
            pass

    user = await chat_service._repo.ensure_daily_credits(message.from_user.id)
    user_lang = user.language if user and user.language else "fa"
    is_admin = is_configured_admin(message.from_user.id)

    welcome_text = (
        f"👋 Welcome to the <b>AI Hub</b>, {message.from_user.first_name}!\n\n"
        "Use the menu below for chat, wallet, VIP, and tools."
        + ("\n\n🛠 Your admin shortcut is ready in the main menu." if is_admin else "")
    ) if user_lang == "en" else (
        f"👋 به <b>هاب هوش مصنوعی</b> خوش آمدید، {message.from_user.first_name}!\n\n"
        "از منوی زیر برای چت، کیف پول، VIP و ابزارها استفاده کنید."
        + ("\n\n🛠 میانبر پنل مدیریت برای شما در منوی اصلی فعال است." if is_admin else "")
    )

    banner_url = "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?q=80&w=1000&auto=format&fit=crop"

    try:
        await message.answer_photo(
            photo=URLInputFile(banner_url),
            caption=welcome_text,
            reply_markup=get_main_menu(user_lang, is_admin=is_admin),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(
            welcome_text,
            reply_markup=get_main_menu(user_lang, is_admin=is_admin),
            parse_mode="HTML",
        )


@base_router.message(Command("new"))
async def cmd_new(message: Message, chat_service: ChatService) -> None:
    if message.from_user is None:
        return

    success = await chat_service.reset_conversation(message.from_user.id)
    if success:
        await message.answer(
            "🔄 Conversation cleared. Let’s start fresh.",
            reply_markup=get_main_menu(is_admin=is_configured_admin(message.from_user.id)),
        )
    else:
        await message.answer("You don't have an active conversation to clear.")
