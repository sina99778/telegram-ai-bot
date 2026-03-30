from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, User
from app.db.repositories.chat_repo import ChatRepository


class ChatService:
    """Thin helper service kept for menu/profile/repository-oriented flows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ChatRepository(session)

    async def reset_conversation(self, telegram_id: int) -> bool:
        stmt = select(User).where(User.telegram_id == telegram_id)
        user: User | None = await self._session.scalar(stmt)
        if user is None:
            return False

        conv_stmt = select(Conversation).where(
            Conversation.user_id == user.id,
            Conversation.is_active.is_(True),
        ).limit(1)
        conversation: Conversation | None = await self._session.scalar(conv_stmt)
        if conversation is None:
            return False

        conversation.is_active = False
        await self._session.commit()
        return True

    async def get_bot_stats(self) -> dict[str, int]:
        return await self._repo.get_bot_stats()
