from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.keyboards.admin_kb import get_admin_main_kb
from app.bot.keyboards.inline import get_profile_keyboard, get_vip_plans_keyboard
from app.bot.keyboards.reply import get_main_menu
from app.core.access import is_configured_admin
from app.core.enums import FeatureName
from app.core.i18n import TEXTS, t
from app.db.models import User
from app.services.chat.group_policy import GroupPolicyService
from app.services.chat.orchestrator import ChatOrchestrator
from app.services.chat_service import ChatService

menu_router = Router(name="menu")

PROFILE_BTNS = {TEXTS["en"]["btn_profile"], TEXTS["fa"]["btn_profile"]}
INVITE_BTNS = {TEXTS["en"]["btn_invite"], TEXTS["fa"]["btn_invite"]}
VIP_BTNS = {TEXTS["en"]["btn_vip"], TEXTS["fa"]["btn_vip"]}
SUPPORT_BTNS = {TEXTS["en"]["btn_support"], TEXTS["fa"]["btn_support"]}
ADMIN_BTNS = {TEXTS["en"]["btn_admin"], TEXTS["fa"]["btn_admin"]}
TOOLS_BTNS = {
    TEXTS["en"]["btn_chat"],
    TEXTS["fa"]["btn_chat"],
    TEXTS["en"]["btn_image"],
    TEXTS["fa"]["btn_image"],
}


def _profile_text(user: User) -> str:
    vip_status = f"ACTIVE until {user.vip_expire_date:%Y-%m-%d}" if user.has_active_vip and user.vip_expire_date else (
        "ACTIVE" if user.has_active_vip else "INACTIVE"
    )
    current_model = str(user.preferred_text_model).upper() if user.preferred_text_model else "FLASH"
    memory = "Keep History" if user.keep_chat_history else "Auto-Clear"
    return (
        "👛 <b>Wallet & Profile</b>\n\n"
        f"Name: {user.first_name or user.username or 'unknown'}\n"
        f"ID: <code>{user.telegram_id}</code>\n\n"
        f"💬 Normal credits: <code>{user.normal_credits}</code>\n"
        f"💎 VIP credits: <code>{user.vip_credits}</code>\n"
        f"✨ VIP access: <b>{vip_status}</b>\n"
        f"🤖 Preferred model: <b>{current_model}</b>\n"
        f"🧠 Memory: <b>{memory}</b>"
    )


@menu_router.message(F.text.in_({TEXTS["en"]["btn_lang"], TEXTS["fa"]["btn_lang"]}))
async def toggle_lang(message: Message, chat_service: ChatService) -> None:
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    user.language = "en" if user.language == "fa" else "fa"
    await chat_service._session.commit()
    await message.answer(
        t("lang_changed", user.language),
        reply_markup=get_main_menu(user.language, is_admin=is_configured_admin(message.from_user.id)),
    )


@menu_router.message(F.text.in_(ADMIN_BTNS), F.chat.type == "private")
async def menu_admin_entry(message: Message, session, db_user: User) -> None:
    if not is_configured_admin(message.from_user.id):
        return
    await message.answer(
        "🛠 <b>Admin Panel</b>\n\nChoose a section below.",
        parse_mode="HTML",
        reply_markup=get_admin_main_kb(),
    )


@menu_router.message(F.text.in_(INVITE_BTNS), F.chat.type == "private")
async def menu_invite(message: Message, chat_service: ChatService) -> None:
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)
    bot_info = await message.bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start=ref_{user.telegram_id}" if user else ""
    await message.answer(
        "🎁 <b>Invite & Earn</b>\n\n"
        f"Friends invited: <code>{user.total_invites if user else 0}</code>\n"
        f"Reward images left: <code>{user.special_reward_images_left if user else 0}</code>\n\n"
        f"Your invite link:\n<code>{invite_link}</code>",
        parse_mode="HTML",
    )


@menu_router.message(F.text.in_(PROFILE_BTNS), F.chat.type == "private")
async def menu_profile(message: Message, chat_service: ChatService) -> None:
    user = await chat_service._repo.ensure_daily_credits(message.from_user.id)
    if not user:
        return
    await message.answer(_profile_text(user), reply_markup=get_profile_keyboard(user), parse_mode="HTML")


@menu_router.message(F.text.in_(VIP_BTNS), F.chat.type == "private")
async def show_vip_plans(message: Message) -> None:
    text = (
        "✨ <b>VIP & Pro Access</b>\n\n"
        "VIP unlocks Pro in private chat, but every Pro message still consumes VIP credits.\n\n"
        "💳 Starter: 150 VIP credits - <code>$1.99</code>\n"
        "🔥 Popular: 700 VIP credits - <code>$6.99</code>\n"
        "👑 Pro Pack: 1800 VIP credits - <code>$14.99</code>"
    )
    await message.answer(text, reply_markup=get_vip_plans_keyboard(), parse_mode="HTML")


@menu_router.message(F.text.in_(SUPPORT_BTNS))
async def menu_support(message: Message) -> None:
    await message.answer(
        "🆘 <b>Support</b>\n\nFor billing, VIP, or technical issues contact:\n\n@ThereIsStillSina",
        parse_mode="HTML",
    )


@menu_router.message(F.text.in_(TOOLS_BTNS), F.chat.type == "private")
async def menu_tools(message: Message, chat_service: ChatService) -> None:
    user = await chat_service._repo.get_user_by_telegram_id(message.from_user.id)
    if message.text in {TEXTS["en"]["btn_chat"], TEXTS["fa"]["btn_chat"]}:
        await message.answer("💬 Send any message and I’ll reply.")
        return

    if user and (user.has_active_vip or user.vip_credits >= 10):
        await message.answer(
            "🖼 <b>Image Lab</b>\n\nUse <code>/image your prompt</code> in private chat.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "🖼 <b>Image Lab</b> needs VIP access or enough VIP credits.",
            parse_mode="HTML",
        )


@menu_router.message(Command("ai"), F.chat.type.in_({"group", "supergroup"}))
async def handle_group_ai_command(
    message: Message,
    command: CommandObject,
    db_user: User,
    chat_orchestrator: ChatOrchestrator,
    group_policy_service: GroupPolicyService,
):
    if not command.args:
        return await message.reply(
            "💬 <b>Group AI Usage</b>\n\nUse <code>/ai your question</code>.",
            parse_mode="HTML",
        )

    decision = group_policy_service.evaluate(
        group_id=message.chat.id,
        user_id=db_user.id,
        prompt=command.args,
    )
    if not decision.allowed:
        return await message.reply(decision.reason, parse_mode="HTML")

    processing_msg = await message.reply("💬 <i>Thinking with Flash-Lite…</i>", parse_mode="HTML")
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
        await processing_msg.edit_text(result.text or "An error occurred.", parse_mode="HTML")
