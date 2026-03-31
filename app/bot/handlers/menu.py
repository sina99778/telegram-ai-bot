from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.keyboards.admin_kb import get_admin_main_kb
from app.bot.keyboards.inline import (
    get_support_menu_keyboard,
    get_vip_menu_keyboard,
    get_wallet_menu_keyboard,
)
from app.bot.keyboards.reply import get_main_menu
from app.core.access import is_configured_admin
from app.core.enums import FeatureName
from app.core.i18n import t
from app.db.models import User
from app.db.repositories.chat_repo import ChatRepository
from app.services.chat.group_policy import GroupPolicyService
from app.services.chat.orchestrator import ChatOrchestrator

menu_router = Router(name="menu")


def _labels(key: str) -> set[str]:
    return {t("fa", key), t("en", key)}


PROFILE_BTNS = _labels("buttons.wallet")
INVITE_BTNS = _labels("buttons.invite")
VIP_BTNS = _labels("buttons.vip")
SUPPORT_BTNS = _labels("buttons.support")
CODES_BTNS = _labels("buttons.codes")
ADMIN_BTNS = _labels("buttons.admin")
LANG_BTNS = _labels("buttons.language")
TOOLS_BTNS = _labels("buttons.chat") | _labels("buttons.image")


def _user_lang(user: User | None) -> str:
    return user.language if user and user.language else "fa"


def _profile_text(user: User) -> str:
    lang = _user_lang(user)
    vip_until = user.active_vip_until
    vip_status = (
        t(lang, "profile.vip.active_until", date=vip_until.strftime("%Y-%m-%d"))
        if user.has_active_vip and vip_until
        else (t(lang, "profile.vip.active") if user.has_active_vip else t(lang, "profile.vip.inactive"))
    )
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    memory = t(lang, "profile.memory.keep") if user.keep_chat_history else t(lang, "profile.memory.clear")
    display_name = user.first_name or user.username or "unknown"
    return "\n".join(
        [
            t(lang, "profile.title"),
            "",
            t(lang, "profile.name", value=display_name),
            t(lang, "profile.id", value=user.telegram_id),
            "",
            t(lang, "profile.normal_credits", value=user.normal_credits),
            t(lang, "profile.vip_credits", value=user.vip_credits),
            t(lang, "profile.vip_status", value=vip_status),
            t(lang, "profile.model", value=current_model),
            t(lang, "profile.memory", value=memory),
        ]
    )


@menu_router.message(F.text.in_(LANG_BTNS), F.chat.type == "private")
async def toggle_lang(message: Message, chat_repo: ChatRepository, db_user: User) -> None:
    next_lang = "en" if _user_lang(db_user) == "fa" else "fa"
    user = await chat_repo.set_user_language(message.from_user.id, next_lang)
    lang = _user_lang(user)
    await message.answer(
        t(lang, "start.language_saved"),
        reply_markup=get_main_menu(lang, is_admin=is_configured_admin(message.from_user.id)),
    )


@menu_router.message(F.text.in_(ADMIN_BTNS), F.chat.type == "private")
async def menu_admin_entry(message: Message, db_user: User) -> None:
    if not is_configured_admin(message.from_user.id):
        return
    lang = _user_lang(db_user)
    await message.answer(
        f"{t(lang, 'admin.panel_title')}\n\n{t(lang, 'admin.panel_subtitle')}",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(lang),
    )


@menu_router.message(F.text.in_(INVITE_BTNS), F.chat.type == "private")
async def menu_invite(message: Message, chat_repo: ChatRepository) -> None:
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


@menu_router.message(F.text.in_(PROFILE_BTNS), F.chat.type == "private")
async def menu_wallet(message: Message, chat_repo: ChatRepository) -> None:
    user = await chat_repo.ensure_daily_credits(message.from_user.id)
    if not user:
        return
    lang = _user_lang(user)
    await message.answer(
        t(lang, "wallet.menu_intro"),
        parse_mode="HTML",
        reply_markup=get_wallet_menu_keyboard(lang),
    )


@menu_router.message(F.text.in_(VIP_BTNS), F.chat.type == "private")
async def show_vip_menu(message: Message, db_user: User) -> None:
    lang = _user_lang(db_user)
    await message.answer(t(lang, "vip.menu"), reply_markup=get_vip_menu_keyboard(lang), parse_mode="HTML")


@menu_router.message(F.text.in_(SUPPORT_BTNS), F.chat.type == "private")
async def menu_support(message: Message, db_user: User) -> None:
    lang = _user_lang(db_user)
    await message.answer(t(lang, "support.menu"), parse_mode="HTML", reply_markup=get_support_menu_keyboard(lang))


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


@menu_router.message(F.text.in_(TOOLS_BTNS), F.chat.type == "private")
async def menu_tools(message: Message, chat_repo: ChatRepository) -> None:
    user = await chat_repo.get_user_by_telegram_id(message.from_user.id)
    lang = _user_lang(user)
    if message.text in _labels("buttons.chat"):
        await message.answer(t(lang, "tools.chat_hint"))
        return
    if user and (user.has_active_vip or user.vip_credits >= 10):
        await message.answer(t(lang, "tools.image_private"), parse_mode="HTML")
    else:
        await message.answer(t(lang, "tools.image_locked"), parse_mode="HTML")


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
        return await message.reply(t(lang, "group.command_help"), parse_mode="HTML")

    decision = group_policy_service.evaluate(
        group_id=message.chat.id,
        user_id=db_user.id,
        prompt=command.args,
        lang=lang,
    )
    if not decision.allowed:
        return await message.reply(decision.reason, parse_mode="HTML")

    processing_msg = await message.reply(t(lang, "group.thinking"), parse_mode="HTML")
    result = await chat_orchestrator.process_message(
        user_id=db_user.id,
        prompt=command.args,
        feature_name=FeatureName.FLASH_TEXT,
        allow_vip=False,
    )
    if result.success:
        group_policy_service.record_usage(group_id=message.chat.id, user_id=db_user.id)
        await processing_msg.edit_text(result.text, parse_mode="HTML")
    else:
        await processing_msg.edit_text(result.text or t(lang, "errors.delivery_failed"), parse_mode="HTML")
