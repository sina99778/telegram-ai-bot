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
        """Handles standard chat messages, enforcing bot economy (Pro vs Flash pricing)."""
        from app.core.config import settings
        # 1. Ensure credits & get user preference
        user = await self._repo.ensure_daily_credits(telegram_id)
        if not user:
            user = await self._repo.get_or_create_user(telegram_id, username, first_name)
        
        # 2. Economy & Model Routing
        # Cost definitions (can be moved to config later if needed)
        PRO_COST_PREMIUM = 7
        FLASH_COST_NORMAL = 1
        
        target_model_str: str = ""
        final_cost: int = 0
        deduct_from_premium: bool = False
        
        # Scenario A: User prefers Pro Model
        if user.preferred_text_model == 'pro':
            target_model_str = settings.GEMINI_MODEL_PRO
            final_cost = PRO_COST_PREMIUM
            deduct_from_premium = True
            
            # Check premium credits
            if user.premium_credits < PRO_COST_PREMIUM:
                return (
                    f"⚠️ <b>Not enough Premium Credits!</b>\n\n"
                    f"You have selected <b>Gemini 3.1 Pro</b>, which costs {PRO_COST_PREMIUM} Premium Credits per message.\n"
                    f"You have {user.premium_credits} Premium Credits.\n\n"
                    f"Please switch back to the 'Flash' model in /profile, purchase credits, or invite friends."
                )
        
        # Scenario B: User prefers Normal Flash Model
        else: 
            target_model_str = settings.GEMINI_MODEL_NORMAL
            final_cost = FLASH_COST_NORMAL
            
            # Use Normal credits if available
            if user.normal_credits >= FLASH_COST_NORMAL:
                deduct_from_premium = False
            # Use Premium credits as fallback if user has them
            elif user.premium_credits >= FLASH_COST_NORMAL:
                deduct_from_premium = True
            else:
                return (
                    "⚠️ <b>Out of Daily Credits!</b>\n\n"
                    "Please wait for the daily reset, purchase VIP, or invite friends to earn credits."
                )

        # 3. Deduct Credits and Commit
        if deduct_from_premium:
            user.premium_credits -= final_cost
        else:
            user.normal_credits -= final_cost
        
        await self._session.commit()

        # 4. Standard Message handling (keep repo logging)
        conversation = await self._repo.get_or_create_active_conversation(user_id=user.id)
        db_content = f"[Attached Media: {mime_type}]\n{text}" if media_bytes else text
        await self._repo.add_message(conversation_id=conversation.id, role="user", content=db_content)
        
        # AI Generation Call (Pass target model explicitly)
        system_prompt = self._builder.get_system_instruction()
        history = await self._repo.get_conversation_history(conversation_id=conversation.id)
        if history and history[-1].role == "user": 
            history = history[:-1] # Remove last user message from history for ai_builder

        messages = self._builder.build_messages(
            system_prompt=system_prompt, history=history, current_user_message=text,
            media_bytes=media_bytes, mime_type=mime_type,
        )

        try:
            # IMPORTANT: Pass the determined model string
            ai_response_text = await self._ai.generate_response(messages, override_model=target_model_str)
        except AIException:
            # Handle AI fail (consider refunding credits here if important)
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
