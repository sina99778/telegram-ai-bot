from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyKeyboardRemove

from app.core.config import settings
from app.core.i18n import t
from app.db.models import User
from app.services.chat.group_policy import GroupPolicyService
from app.services.security.abuse_guard import AbuseGuardService
from app.services.search.search_service import SearchService
from app.services.security.content_filter import ContentFilterService

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
    length_check = AbuseGuardService.enforce_prompt_length(prompt=query, limit=settings.SEARCH_MAX_QUERY_LENGTH, lang=lang)
    if not length_check.allowed:
        await message.reply(length_check.reason, parse_mode="HTML")
        return
    content_check = ContentFilterService.check_text_prompt(query)
    if not content_check.allowed:
        await AbuseGuardService.record_failure(subject="user_search", subject_id=db_user.id)
        await message.reply(t(lang, "abuse.content_blocked"), parse_mode="HTML")
        return
    throttle = await AbuseGuardService.check_search(scope_id=db_user.id, is_group=False, lang=lang)
    if not throttle.allowed:
        await message.reply(throttle.reason, parse_mode="HTML")
        return

    processing_msg = await message.reply(t(lang, "search.processing"), parse_mode="HTML")
    result = await search_service.search_for_user(user=db_user, query=query)
    if not result.success:
        await AbuseGuardService.record_failure(subject="user_search", subject_id=db_user.id)
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
    length_check = AbuseGuardService.enforce_prompt_length(prompt=query, limit=settings.SEARCH_MAX_QUERY_LENGTH, lang=lang)
    if not length_check.allowed:
        await message.reply(length_check.reason, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return
    content_check = ContentFilterService.check_text_prompt(query)
    if not content_check.allowed:
        await AbuseGuardService.record_failure(subject="group_search", subject_id=message.chat.id)
        await message.reply(t(lang, "abuse.content_blocked"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return

    if not group_policy_service.claim_message(group_id=message.chat.id, message_id=message.message_id):
        return

    throttle = await AbuseGuardService.check_search(scope_id=message.chat.id, is_group=True, lang=lang)
    if not throttle.allowed:
        await message.reply(throttle.reason, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return

    cooldown = group_policy_service.check_cooldown(group_id=message.chat.id, user_id=db_user.id, lang=lang)
    if not cooldown.allowed:
        await message.reply(cooldown.reason, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return

    processing_msg = await message.reply(t(lang, "search.processing"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    result = await search_service.search_for_group(user=db_user, group_id=message.chat.id, query=query)
    if result.success:
        group_policy_service.record_cooldown(group_id=message.chat.id, user_id=db_user.id)
    else:
        await AbuseGuardService.record_failure(subject="group_search", subject_id=message.chat.id)
    await processing_msg.edit_text(result.text, parse_mode="HTML")
