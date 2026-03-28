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

        user = await self._repo.get_or_create_user(telegram_id=telegram_id, username=username, first_name=first_name)
        conversation = await self._repo.get_or_create_active_conversation(user_id=user.id)

        db_content = text
        if media_bytes:
            db_content = f"[Attached Media: {mime_type}]\n{text}"

        await self._repo.add_message(conversation_id=conversation.id, role="user", content=db_content)

        history = await self._repo.get_conversation_history(conversation_id=conversation.id)
        
        if history and history[-1].role == "user":
            history = history[:-1]

        system_prompt: str = self._builder.get_system_instruction()

        messages = self._builder.build_messages(
            system_prompt=system_prompt,
            history=history,
            current_user_message=text,
            media_bytes=media_bytes,
            mime_type=mime_type,
        )

        try:
            ai_response_text: str = await self._ai.generate_response(messages)
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
