from __future__ import annotations

import logging
from datetime import datetime, timezone

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
        # FIX: Check if the user is VIP AND hasn't explicitly downgraded to FLASH
        is_flash_preferred = str(user.preferred_text_model).upper() == "FLASH"
        use_pro_model = user.is_vip and not is_flash_preferred
        
        # EXACT MODEL STRINGS ACCORDING TO GOOGLE API DOCS:
        target_model_str = "gemini-3.1-pro-preview" if use_pro_model else "gemini-2.5-flash"

        # Apply Economy Pricing
        if use_pro_model:
            cost = 5 # CHANGED: Now 5 credits per Pro chat
            if user.premium_credits < cost:
                return f"⚠️ <b>Not enough credits!</b>\n\nGemini 3.1 Pro requires {cost} credits per message. You have {user.premium_credits} credits left. Please recharge or switch to the Free Flash model."
            user.premium_credits -= cost
        else:
            cost = 1
            if user.normal_credits >= cost:
                user.normal_credits -= cost
            elif user.premium_credits >= cost:
                user.premium_credits -= cost
            else:
                return "⚠️ <b>Out of Credits!</b>\n\nYou have used your daily limit. Please invite friends or purchase VIP to continue."
        
        await self._session.commit()

        # 3. Standard DB Logging & Generation
        conversation = await self._repo.get_or_create_active_conversation(user_id=user.id)
        history = await self._repo.get_conversation_history(conversation_id=conversation.id)

        # --- Token Optimization & Auto-Reset ---
        was_auto_reset = False
        if history and hasattr(history[-1], 'created_at') and history[-1].created_at:
            last_time = history[-1].created_at
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
                
            # Auto-clear only if memory is OFF
            if not user.keep_chat_history:
                if (datetime.now(timezone.utc) - last_time).total_seconds() > 7200: # 2 hours timeout
                    await self.reset_conversation(telegram_id)
                    conversation = await self._repo.get_or_create_active_conversation(user_id=user.id)
                    history = []
                    was_auto_reset = True

        # --- SMART TRUNCATION (VIP vs FREE) ---
        # 1 interaction = 2 messages (user + bot)
        max_messages = 10 # Default for memory OFF (5 interactions context during the 2 hours)
        
        if user.keep_chat_history:
            if user.is_vip:
                max_messages = 40 # 20 interactions (prevents Google API context length crash)
            else:
                max_messages = 4 # 2 interactions ONLY for Free users
                
        if len(history) > max_messages:
            history = history[-max_messages:]
        # --------------------------------------

        db_content = f"[Attached Media: {mime_type}]\n{text}" if media_bytes else text
        await self._repo.add_message(conversation_id=conversation.id, role="user", content=db_content)

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
            # IMPORTANT: Pass the determined model string
            ai_response_text = await self._ai.generate_response(messages, override_model=target_model_str)
        except AIException as e:
            logger.error(f"AI Error: {e}")
            # Handle AI fail (consider refunding credits here if important)
            return _AI_ERROR_REPLY

        await self._repo.add_message(conversation_id=conversation.id, role="model", content=ai_response_text)
        
        # Notify user if their context was cleared
        if was_auto_reset:
            ai_response_text = "🧹 <i>Your previous session expired due to inactivity. Starting a fresh conversation!</i>\n\n" + ai_response_text
            
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
        """Handles image generation request, deducting premium credits or special rewards."""
        user = await self._repo.ensure_daily_credits(telegram_id)
        if not user:
            return "User not found."

        cost = 10 # CHANGED: Now 10 premium credits per image
        used_special_reward = False

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        # Check Special Reward allowance first
        if user.special_reward_images_left > 0 and user.special_reward_expire and user.special_reward_expire > now:
            user.special_reward_images_left -= 1
            used_special_reward = True
        elif user.premium_credits >= cost:
            user.premium_credits -= cost
        else:
             return f"⚠️ <b>Not enough Premium Credits!</b>\n\nImagen 3 requires {cost} credits per image. You have {user.premium_credits}. Please purchase more."

        await self._session.commit()

        image_result = await self._ai.generate_image(prompt)
        
        # If the result is a string, it means an error occurred
        if isinstance(image_result, str):
            # Refund the user
            if used_special_reward:
                user.special_reward_images_left += 1
            else:
                user.premium_credits += cost
            await self._session.commit()
            return f"⚠️ <b>Generation Failed.</b>\n\nReason:\n<code>{image_result}</code>\n\n<i>Your credits have been refunded.</i>"

        return image_result
