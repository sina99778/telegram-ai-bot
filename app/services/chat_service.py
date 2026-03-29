from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AIException, GeminiClient
from app.ai.prompt_builder import PromptBuilder
from app.db.models import Conversation, User
from app.db.repositories.chat_repo import ChatRepository

logger = logging.getLogger(__name__)

_AI_ERROR_REPLY: str = "⚠️ Sorry, I'm having trouble connecting to the AI service right now. Please try again in a moment."

class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session
        self._repo: ChatRepository = ChatRepository(session)
        self._ai: GeminiClient = GeminiClient()
        self._builder: PromptBuilder = PromptBuilder()

    async def process_user_message(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        text: str,
        media_bytes: bytes | None = None,
        mime_type: str | None = None,
    ) -> str:
        # 1. Ensure daily credits & get user
        user = await self._repo.ensure_daily_credits(telegram_id)
        if not user:
            user = await self._repo.get_or_create_user(telegram_id, username, first_name)

        # 2. Model Routing & Credit Check
        use_pro_model = user.is_vip
        target_model = "gemini-3.1-pro" if use_pro_model else "gemini-2.5-flash"

        if use_pro_model:
            if user.premium_credits <= 0:
                return "⚠️ <b>Out of Premium Credits!</b>\n\nYou have exhausted your VIP credits. Please use the referral system to earn more, or wait for the daily reset."
            user.premium_credits -= 1
        else:
            if user.normal_credits <= 0:
                return "⚠️ <b>Out of Normal Credits!</b>\n\nYou have used your 50 free messages for today. Please upgrade to VIP or wait until tomorrow."
            user.normal_credits -= 1

        await self._session.commit()

        # 3. Standard DB Logging & Generation
        conversation = await self._repo.get_or_create_active_conversation(user_id=user.id)
        db_content = f"[Attached Media: {mime_type}]\n{text}" if media_bytes else text
        await self._repo.add_message(conversation_id=conversation.id, role="user", content=db_content)

        history = await self._repo.get_conversation_history(conversation_id=conversation.id)
        if history and history[-1].role == "user":
            history = history[:-1]

        system_prompt = self._builder.get_system_instruction()
        messages = self._builder.build_messages(
            system_prompt=system_prompt,
            history=history,
            current_user_message=text,
            media_bytes=media_bytes,
            mime_type=mime_type,
        )

        try:
            ai_response_text = await self._ai.generate_response(messages, override_model=target_model)
        except AIException:
            logger.error("AI service unavailable for user %d", telegram_id)
            return _AI_ERROR_REPLY

        await self._repo.add_message(conversation_id=conversation.id, role="model", content=ai_response_text)
        return ai_response_text

    async def reset_conversation(self, telegram_id: int) -> bool:
        stmt = select(User).where(User.telegram_id == telegram_id)
        user: User | None = await self._session.scalar(stmt)

        if user is None:
            return False

        conv_stmt = select(Conversation).where(Conversation.user_id == user.id, Conversation.is_active.is_(True)).limit(1)
        conversation: Conversation | None = await self._session.scalar(conv_stmt)

        if conversation is None:
            return False

        conversation.is_active = False
        await self._session.commit()
        return True

    async def get_bot_stats(self) -> dict[str, int]:
        return await self._repo.get_bot_stats()

    async def generate_image_for_user(self, telegram_id: int, prompt: str) -> bytes | str:
        """Handles image generation request, deducting premium credits."""
        user = await self._repo.ensure_daily_credits(telegram_id)
        if not user:
            return "User not found."

        if user.premium_credits <= 0:
            return "⚠️ <b>Not enough Premium Credits!</b>\n\nImage generation requires Premium Credits. Please upgrade to VIP or invite friends."

        user.premium_credits -= 1
        await self._session.commit()

        image_bytes = await self._ai.generate_image(prompt)
        if not image_bytes:
            # Refund if failed
            user.premium_credits += 1
            await self._session.commit()
            return "⚠️ <b>Generation Failed.</b>\n\nThe AI couldn't generate an image for this prompt. Your credit has been refunded."

        return image_bytes
