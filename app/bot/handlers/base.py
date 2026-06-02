from __future__ import annotations

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, URLInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import get_language_picker_keyboard
from app.bot.keyboards.reply import get_main_menu
from app.core.access import is_configured_admin
from app.core.i18n import t
from app.core import premium_emoji
from app.db.models import User
from app.db.repositories.chat_repo import ChatRepository

logger = logging.getLogger(__name__)

base_router = Router(name="base")

BANNER_URL = "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?q=80&w=1000&auto=format&fit=crop"
BANNER_FETCH_TIMEOUT = 5.0


def _main_menu_text(lang: str, first_name: str, is_admin: bool) -> str:
    lines = [
        t(lang, "main.welcome", name=html.escape(first_name or "")),
        "",
        t(lang, "main.subtitle"),
    ]
    if is_admin:
        lines.extend(["", t(lang, "main.admin_hint")])
    return "\n".join(lines)


@base_router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, chat_repo: ChatRepository, session: AsyncSession) -> None:
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
    kb = get_main_menu(lang, is_admin=is_admin)
    welcome_text = _main_menu_text(lang, message.from_user.first_name or "friend", is_admin)
    # Optional premium emoji; falls back to the plain text if rendering is
    # rejected (e.g. bot owner has no Telegram Premium).
    fancy_text = await premium_emoji.decorate(session, welcome_text)

    async def _send(text: str) -> bool:
        try:
            await asyncio.wait_for(
                message.answer_photo(photo=URLInputFile(BANNER_URL), caption=text, reply_markup=kb, parse_mode="HTML"),
                timeout=BANNER_FETCH_TIMEOUT,
            )
            return True
        except Exception:
            # Banner slow/unavailable, or caption rejected → try text-only.
            try:
                await message.answer(text, reply_markup=kb, parse_mode="HTML")
                return True
            except Exception:
                return False

    if not await _send(fancy_text):
        # Last resort: the plain (non-premium) text always works.
        logger.warning("Start: premium/banner send failed telegram_id=%s; sending plain text", message.from_user.id)
        try:
            await message.answer(welcome_text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            logger.warning("Start: plain welcome send also failed telegram_id=%s", message.from_user.id, exc_info=True)


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
