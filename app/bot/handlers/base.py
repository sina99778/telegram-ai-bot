from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, URLInputFile

from app.bot.keyboards.inline import get_language_picker_keyboard
from app.bot.keyboards.reply import get_main_menu
from app.core.access import is_configured_admin
from app.core.i18n import t
from app.db.models import User
from app.db.repositories.chat_repo import ChatRepository

base_router = Router(name="base")

BANNER_URL = "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?q=80&w=1000&auto=format&fit=crop"


def _main_menu_text(lang: str, first_name: str, is_admin: bool) -> str:
    lines = [
        t(lang, "main.welcome", name=first_name),
        "",
        t(lang, "main.subtitle"),
    ]
    if is_admin:
        lines.extend(["", t(lang, "main.admin_hint")])
    return "\n".join(lines)


@base_router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, chat_repo: ChatRepository) -> None:
    if message.from_user is None:
        return

    if message.chat.type in {"group", "supergroup"}:
        await message.answer(
            t("fa", "group.private_only"),
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    user = await chat_repo.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    payload = command.args
    if payload and payload.startswith("ref_"):
        try:
            referrer_tg_id = int(payload.split("_")[1])
            await chat_repo.process_referral(message.from_user.id, referrer_tg_id)
        except ValueError:
            pass

    user = await chat_repo.ensure_daily_credits(message.from_user.id)
    is_admin = is_configured_admin(message.from_user.id)

    if not user or not user.language:
        await message.answer(
            t("fa", "start.choose_language"),
            reply_markup=get_language_picker_keyboard(),
            parse_mode="HTML",
        )
        return

    lang = user.language
    welcome_text = _main_menu_text(lang, message.from_user.first_name or "friend", is_admin)
    try:
        await message.answer_photo(
            photo=URLInputFile(BANNER_URL),
            caption=welcome_text,
            reply_markup=get_main_menu(lang, is_admin=is_admin),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(
            welcome_text,
            reply_markup=get_main_menu(lang, is_admin=is_admin),
            parse_mode="HTML",
        )


@base_router.callback_query(F.data.startswith("lang:set:"))
async def cb_set_language(callback: CallbackQuery, chat_repo: ChatRepository) -> None:
    if callback.from_user is None:
        return
    lang = callback.data.split(":")[-1]
    user = await chat_repo.set_user_language(callback.from_user.id, lang)
    is_admin = is_configured_admin(callback.from_user.id)
    if not user:
        return await callback.answer(t("en", "errors.user_not_found"), show_alert=True)

    await callback.message.edit_text(
        f"{t(lang, 'start.language_saved')}\n\n{_main_menu_text(lang, callback.from_user.first_name or 'friend', is_admin)}",
        parse_mode="HTML",
    )
    await callback.message.answer(
        _main_menu_text(lang, callback.from_user.first_name or "friend", is_admin),
        reply_markup=get_main_menu(lang, is_admin=is_admin),
        parse_mode="HTML",
    )
    await callback.answer()


@base_router.message(Command("new"))
async def cmd_new(message: Message, chat_repo: ChatRepository, db_user: User | None = None) -> None:
    if message.from_user is None:
        return
    if message.chat.type in {"group", "supergroup"}:
        await message.answer(
            t(db_user.language if db_user and db_user.language else "fa", "group.private_only"),
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    lang = db_user.language if db_user and db_user.language else "fa"
    success = await chat_repo.reset_active_conversation(message.from_user.id)
    if success:
        await message.answer(
            t(lang, "start.new_chat_reset"),
            reply_markup=get_main_menu(lang, is_admin=is_configured_admin(message.from_user.id)),
        )
    else:
        await message.answer(t(lang, "start.new_chat_missing"))
