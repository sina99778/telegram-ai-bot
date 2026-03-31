from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyKeyboardRemove

from app.core.i18n import t
from app.db.models import User
from app.services.chat.group_policy import GroupPolicyService
from app.services.search.search_service import SearchService

search_router = Router(name="search")


def _lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


@search_router.message(Command("search"), F.chat.type == "private")
async def handle_private_search(
    message: Message,
    command: CommandObject,
    db_user: User,
    search_service: SearchService,
) -> None:
    lang = _lang(db_user)
    query = (command.args or "").strip()
    if not query:
        await message.reply(t(lang, "search.usage"), parse_mode="HTML")
        return

    processing_msg = await message.reply(t(lang, "search.processing"), parse_mode="HTML")
    result = await search_service.search_for_user(user=db_user, query=query)
    await processing_msg.edit_text(result.text, parse_mode="HTML")


@search_router.message(Command("search"), F.chat.type.in_({"group", "supergroup"}))
async def handle_group_search(
    message: Message,
    command: CommandObject,
    db_user: User,
    search_service: SearchService,
    group_policy_service: GroupPolicyService,
) -> None:
    lang = _lang(db_user)
    query = (command.args or "").strip()
    if not query:
        await message.reply(t(lang, "search.usage_group"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return

    if not group_policy_service.claim_message(group_id=message.chat.id, message_id=message.message_id):
        return

    cooldown = group_policy_service.check_cooldown(group_id=message.chat.id, user_id=db_user.id, lang=lang)
    if not cooldown.allowed:
        await message.reply(cooldown.reason, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return

    processing_msg = await message.reply(t(lang, "search.processing"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    result = await search_service.search_for_group(user=db_user, group_id=message.chat.id, query=query)
    if result.success:
        group_policy_service.record_cooldown(group_id=message.chat.id, user_id=db_user.id)
    await processing_msg.edit_text(result.text, parse_mode="HTML")
