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

        # Apply new Economy Pricing
        if use_pro_model:
            cost = 7
            if user.premium_credits < cost:
                return f"⚠️ <b>Not enough credits!</b>\n\nGemini 3.1 Pro requires {cost} credits per message. You have {user.premium_credits} credits left. Please recharge."
            user.premium_credits -= cost
        else:
            cost = 1
            if user.normal_credits >= cost:
                user.normal_credits -= cost
            elif user.premium_credits >= cost:
                # Fallback to premium if normal is empty
                user.premium_credits -= cost
            else:
                return "⚠️ <b>Out of Credits!</b>\n\nYou have used your daily limit. Please invite friends or purchase VIP to continue."

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

        cost = 15
        if user.premium_credits < cost:
            return f"⚠️ <b>Not enough Premium Credits!</b>\n\nNano Banana 2 requires {cost} credits per image. You have {user.premium_credits}. Please purchase more."

        user.premium_credits -= cost
        await self._session.commit()

        image_result = await self._ai.generate_image(prompt)
        
        # If the result is a string, it means an error occurred
        if isinstance(image_result, str):
            # Refund the user
            user.premium_credits += cost
            await self._session.commit()
            return f"⚠️ <b>Generation Failed.</b>\n\nReason:\n<code>{image_result}</code>\n\n<i>Your {cost} credits have been refunded.</i>"

        return image_result
