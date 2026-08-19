from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_kb import get_admin_main_kb
from app.services.config.runtime_config import RuntimeConfig
from app.bot.keyboards.inline import (
    get_support_menu_keyboard,
    get_vip_menu_keyboard,
    get_wallet_menu_keyboard,
)
from app.bot.keyboards.reply import get_main_menu
from app.bot.keyboards.styling import strip_leading_emoji
from app.core.access import is_configured_admin
from app.core.enums import FeatureName
from app.core.i18n import t
from app.db.models import User
from app.db.repositories.chat_repo import ChatRepository
from app.bot.handlers.chat import finalize_group_response
from app.services.security.abuse_guard import AbuseGuardService
from app.services.chat.group_policy import GroupPolicyService
from app.services.chat.orchestrator import ChatOrchestrator
import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware, F, Router

menu_router = Router(name="menu")
logger = logging.getLogger(__name__)


class MenuSpamMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        # Prefer the user's saved language (db_user is populated by the outer
        # DB middleware) so throttle messages, if ever surfaced, render in
        # the right locale. Fall back to Persian — the project's default UI.
        db_user = data.get("db_user")
        lang = db_user.language if (db_user and getattr(db_user, "language", None)) else "fa"
        guard = await AbuseGuardService.check_menu_button(user_id=event.from_user.id, lang=lang)
        if not guard.allowed:
            # Silently drop the spam
            return None
        return await handler(event, data)

menu_router.message.middleware(MenuSpamMiddleware())


def _labels(key: str) -> set[str]:
    """Both languages, AND an emoji-stripped variant of each.

    Reply-keyboard buttons route by the text the user sends. When premium icons
    are enabled the leading emoji is moved off the label into the button's icon
    (see keyboards/styling.py), so the sent text loses its emoji. Including the
    stripped variant here keeps routing working whether the emoji is present or
    not — so turning premium icons on/off can never break the bottom menu."""
    raw = {t("fa", key), t("en", key)}
    return raw | {strip_leading_emoji(label) for label in raw}


WALLET_BTNS = _labels("buttons.wallet")
PROFILE_BTNS = _labels("buttons.profile")
PRO_BTNS = _labels("buttons.pro")
INVITE_BTNS = _labels("buttons.invite")
VIP_BTNS = _labels("buttons.vip")
SUPPORT_BTNS = _labels("buttons.support")
GUIDE_BTNS = _labels("buttons.guide")
CODES_BTNS = _labels("buttons.codes")
ADMIN_BTNS = _labels("buttons.admin")
LANG_BTNS = _labels("buttons.language")
SEARCH_BTNS = _labels("buttons.search")
IMAGE_BTNS = _labels("buttons.image")
IMAGE_EDIT_BTNS = _labels("buttons.image_edit")
TOOLS_BTNS = _labels("buttons.chat")


def _user_lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


def _private_help_text(lang: str, *, is_admin: bool, free_images: int) -> str:
    lines = [
        t(lang, "help.private.title"),
        t(lang, "help.private.subtitle"),
        "",
        t(lang, "help.private.chat"),
        t(lang, "help.private.search"),
        t(lang, "help.private.image", free_images=free_images),
        t(lang, "help.private.wallet"),
        t(lang, "help.private.vip"),
        t(lang, "help.private.invite"),
        t(lang, "help.private.support"),
        t(lang, "help.private.language"),
        t(lang, "help.private.antispam"),
    ]
    if is_admin:
        lines.append(t(lang, "help.private.admin"))
    return "\n".join(lines)


def _group_help_text(lang: str, *, group_search: int) -> str:
    return "\n".join(
        [
            t(lang, "help.group.title"),
            t(lang, "help.group.subtitle"),
            "",
            t(lang, "help.group.trigger"),
            t(lang, "help.group.ai"),
            t(lang, "help.group.search", group_search=group_search),
            t(lang, "help.group.limit"),
            t(lang, "help.group.cooldown"),
            t(lang, "help.group.private_only"),
        ]
    )


from aiogram.fsm.context import FSMContext
from app.bot.states import ActionStates
from app.bot.keyboards.styling import colorize_inline_markup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.services.usage.quota_service import QuotaService


@menu_router.message(F.text.in_(LANG_BTNS), F.chat.type == "private")
async def toggle_lang(message: Message, chat_repo: ChatRepository, db_user: User, state: FSMContext) -> None:
    await state.clear()
    next_lang = "en" if _user_lang(db_user) == "fa" else "fa"
    user = await chat_repo.set_user_language(message.from_user.id, next_lang)
    lang = _user_lang(user)
    await message.answer(
        t(lang, "start.language_saved"),
        reply_markup=get_main_menu(lang, is_admin=is_configured_admin(message.from_user.id)),
    )


@menu_router.message(F.text.in_(ADMIN_BTNS), F.chat.type == "private")
async def menu_admin_entry(message: Message, db_user: User, state: FSMContext) -> None:
    await state.clear()
    if not is_configured_admin(message.from_user.id):
        return
    lang = _user_lang(db_user)
    await message.answer(
        f"{t(lang, 'admin.panel_title')}\n\n{t(lang, 'admin.panel_subtitle')}",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(lang),
    )


@menu_router.message(F.text.in_(INVITE_BTNS), F.chat.type == "private")
async def menu_invite(message: Message, chat_repo: ChatRepository, state: FSMContext) -> None:
    await state.clear()
    user = await chat_repo.get_user_by_telegram_id(message.from_user.id)
    lang = _user_lang(user)
    bot_info = await message.bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start=ref_{user.telegram_id}" if user else ""
    await message.answer(
        t(
            lang,
            "invite.menu",
            invites=user.total_invites if user else 0,
            images=user.special_reward_images_left if user else 0,
            link=invite_link,
        ),
        parse_mode="HTML",
    )


@menu_router.message(F.text.in_(WALLET_BTNS), F.chat.type == "private")
async def menu_wallet(message: Message, chat_repo: ChatRepository, state: FSMContext) -> None:
    await state.clear()
    user = await chat_repo.ensure_daily_credits(message.from_user.id)
    if not user:
        return
    lang = _user_lang(user)
    await message.answer(
        t(lang, "wallet.menu_intro"),
        parse_mode="HTML",
        reply_markup=get_wallet_menu_keyboard(lang),
    )


@menu_router.message(F.text.in_(PROFILE_BTNS), F.chat.type == "private")
async def menu_profile(message: Message, chat_repo: ChatRepository, state: FSMContext) -> None:
    await state.clear()
    user = await chat_repo.ensure_daily_credits(message.from_user.id)
    if not user:
        return
    from app.bot.handlers.callbacks import _format_profile
    from app.bot.keyboards.inline import get_profile_keyboard
    await message.answer(
        _format_profile(user),
        parse_mode="HTML",
        reply_markup=get_profile_keyboard(user),
    )


@menu_router.message(F.text.in_(PRO_BTNS), F.chat.type == "private")
async def menu_pro(message: Message, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    lang = _user_lang(db_user)
    db_user.preferred_text_model = "PRO"
    await session.commit()
    pro_status = await QuotaService(session).get_free_pro_status_for_user(db_user.id)
    rem = pro_status.remaining
    kb = colorize_inline_markup(InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "buttons.switch_to_flash"), callback_data="switch_model_flash")]]
    ))
    await message.answer(t(lang, "chat.pro_mode_activated", remaining=rem), parse_mode="HTML", reply_markup=kb)


@menu_router.message(F.text.in_(VIP_BTNS), F.chat.type == "private")
async def show_vip_menu(message: Message, db_user: User, state: FSMContext) -> None:
    await state.clear()
    lang = _user_lang(db_user)
    await message.answer(t(lang, "vip.menu"), reply_markup=get_vip_menu_keyboard(lang), parse_mode="HTML")


@menu_router.message(F.text.in_(SUPPORT_BTNS), F.chat.type == "private")
async def menu_support(message: Message, db_user: User, state: FSMContext) -> None:
    await state.clear()
    lang = _user_lang(db_user)
    await message.answer(t(lang, "support.menu"), parse_mode="HTML", reply_markup=get_support_menu_keyboard(lang))


@menu_router.message(F.text.in_(GUIDE_BTNS), F.chat.type == "private")
async def menu_private_help(message: Message, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    lang = _user_lang(db_user)
    free_images = await RuntimeConfig.get_int(session, "free_daily_image")
    await message.answer(
        _private_help_text(lang, is_admin=is_configured_admin(message.from_user.id), free_images=free_images),
        parse_mode="HTML",
    )


@menu_router.message(F.text.in_(SEARCH_BTNS), F.chat.type == "private")
async def menu_search_help(message: Message, db_user: User, state: FSMContext) -> None:
    await state.set_state(ActionStates.waiting_for_search_query)
    lang = _user_lang(db_user)
    cancel_kb = colorize_inline_markup(InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "buttons.cancel"), callback_data="cancel_action")]]
    ))
    await message.answer(t(lang, "search.prompt_input_title"), parse_mode="HTML", reply_markup=cancel_kb)


@menu_router.message(F.text.in_(IMAGE_BTNS), F.chat.type == "private")
async def menu_image_help(message: Message, db_user: User, state: FSMContext) -> None:
    await state.set_state(ActionStates.waiting_for_image_prompt)
    lang = _user_lang(db_user)
    cancel_kb = colorize_inline_markup(InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "buttons.cancel"), callback_data="cancel_action")]]
    ))
    await message.answer(t(lang, "image.prompt_input_title"), parse_mode="HTML", reply_markup=cancel_kb)


@menu_router.message(F.text.in_(IMAGE_EDIT_BTNS), F.chat.type == "private")
async def menu_image_edit_help(message: Message, db_user: User, state: FSMContext) -> None:
    await state.set_state(ActionStates.waiting_for_image_edit)
    lang = _user_lang(db_user)
    cancel_kb = colorize_inline_markup(InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "buttons.cancel"), callback_data="cancel_action")]]
    ))
    await message.answer(t(lang, "image.edit_prompt_input_title"), parse_mode="HTML", reply_markup=cancel_kb)


@menu_router.message(F.text.in_(TOOLS_BTNS), F.chat.type == "private")
async def menu_chat_hint(message: Message, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    lang = _user_lang(db_user)
    db_user.preferred_text_model = "FLASH"
    await session.commit()
    await message.answer(t(lang, "chat.flash_mode_activated"), parse_mode="HTML")


@menu_router.message(F.text.in_(CODES_BTNS), F.chat.type == "private")
async def menu_codes_legacy(message: Message, chat_repo: ChatRepository) -> None:
    user = await chat_repo.ensure_daily_credits(message.from_user.id)
    if not user:
        return
    lang = _user_lang(user)
    await message.answer(
        t(lang, "wallet.menu_intro"),
        parse_mode="HTML",
        reply_markup=get_wallet_menu_keyboard(lang),
    )


@menu_router.message(Command("ai"), F.chat.type.in_({"group", "supergroup"}))
async def handle_group_ai_command(
    message: Message,
    command: CommandObject,
    db_user: User,
    chat_orchestrator: ChatOrchestrator,
    group_policy_service: GroupPolicyService,
):
    lang = _user_lang(db_user)
    if not command.args:
        return await message.reply(t(lang, "group.command_help"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    logger.info("Group pipeline: trigger accepted chat_id=%s message_id=%s via=command_ai", message.chat.id, message.message_id)

    if not group_policy_service.claim_message(group_id=message.chat.id, message_id=message.message_id):
        logger.info("Group pipeline: duplicate skipped chat_id=%s message_id=%s", message.chat.id, message.message_id)
        return
    logger.info("Group pipeline: dedup passed chat_id=%s message_id=%s", message.chat.id, message.message_id)

    anomaly = await AbuseGuardService.check_group_request(group_id=message.chat.id, lang=lang)
    if not anomaly.allowed:
        logger.info("Group pipeline: blocked by anomaly containment chat_id=%s message_id=%s", message.chat.id, message.message_id)
        return await message.reply(anomaly.reason, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

    decision = await group_policy_service.evaluate(
        group_id=message.chat.id,
        user_id=db_user.id,
        prompt=command.args,
        lang=lang,
    )
    if not decision.allowed:
        logger.info("Group pipeline: blocked by policy chat_id=%s message_id=%s", message.chat.id, message.message_id)
        return await message.reply(decision.reason, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    logger.info("Group pipeline: cooldown/policy passed chat_id=%s message_id=%s", message.chat.id, message.message_id)

    processing_msg = await message.reply(t(lang, "group.thinking"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    logger.info("Group pipeline: placeholder sent chat_id=%s message_id=%s", message.chat.id, message.message_id)
    result, delivered = await finalize_group_response(
        trigger_message=message,
        processing_msg=processing_msg,
        generation_coro=chat_orchestrator.process_message(
            user_id=db_user.id,
            prompt=command.args,
            feature_name=FeatureName.FLASH_TEXT,
            allow_vip=False,
        ),
        lang=lang,
    )
    if delivered and result:
        await group_policy_service.record_usage(group_id=message.chat.id, user_id=db_user.id)


@menu_router.message(Command("help"), F.chat.type == "private")
async def command_private_help(message: Message, db_user: User, session: AsyncSession) -> None:
    lang = _user_lang(db_user)
    free_images = await RuntimeConfig.get_int(session, "free_daily_image")
    await message.answer(
        _private_help_text(lang, is_admin=is_configured_admin(message.from_user.id), free_images=free_images),
        parse_mode="HTML",
    )


@menu_router.message(Command("help"), F.chat.type.in_({"group", "supergroup"}))
@menu_router.message(Command("group_help"), F.chat.type.in_({"group", "supergroup"}))
async def command_group_help(message: Message, db_user: User, session: AsyncSession) -> None:
    lang = _user_lang(db_user)
    group_search = await RuntimeConfig.get_int(session, "search_daily_group")
    await message.reply(_group_help_text(lang, group_search=group_search), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
