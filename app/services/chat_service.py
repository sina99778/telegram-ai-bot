"""
app/services/chat_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Core business-logic orchestrator for the Telegram AI bot.

Coordinates the **Repository** (data access), **GeminiClient** (AI),
and **PromptBuilder** (formatting) layers to process user messages
end-to-end.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AIException, GeminiClient
from app.ai.prompt_builder import PromptBuilder
from app.db.models import Conversation, User
from app.db.repositories.chat_repo import ChatRepository

logger = logging.getLogger(__name__)

# Friendly fallback shown to the user when the AI service is down.
_AI_ERROR_REPLY: str = (
    "⚠️ Sorry, I'm having trouble connecting to the AI service right now. "
    "Please try again in a moment."
)


class ChatService:
    """High-level service that wires DB ↔ AI ↔ Prompt layers together.

    Instantiated once per request with a scoped ``AsyncSession``.

    Usage::

        async with async_session() as session:
            service = ChatService(session)
            reply   = await service.process_user_message(
                telegram_id=123456,
                username="johndoe",
                first_name="John",
                text="What's the weather?",
            )
    """

    def __init__(self, session: AsyncSession) -> None:
        # --- Data-access layer ---
        self._session: AsyncSession = session
        self._repo: ChatRepository = ChatRepository(session)

        # --- AI layer ---
        self._ai: GeminiClient = GeminiClient()

        # --- Prompt formatting layer ---
        self._builder: PromptBuilder = PromptBuilder()

    # ──────────────────────────────────────────
    #  Main workflow
    # ──────────────────────────────────────────

    async def process_user_message(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        text: str,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
    ) -> str:
        """Full request lifecycle: persist → build prompt → call AI → persist.

        Parameters
        ----------
        telegram_id:
            Telegram user ID.
        username:
            Telegram ``@username`` (may be ``None``).
        first_name:
            Telegram display name (may be ``None``).
        text:
            The raw message text from the user.
        image_bytes:
            Optional raw bytes of an attached image.  Passed to the
            PromptBuilder but **not** stored in the database to save
            space — only a ``[Attached Image]`` marker is persisted.
        mime_type:
            MIME type of the attached image (default ``"image/jpeg"``).

        Returns
        -------
        str
            The AI model's reply, or a friendly error string if the AI
            service is unreachable.
        """

        # 1️⃣  Resolve (or create) the user in the database.
        user: User = await self._repo.get_or_create_user(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
        )

        # 2️⃣  Resolve (or create) the user's active conversation.
        conversation: Conversation = (
            await self._repo.get_or_create_active_conversation(user_id=user.id)
        )

        # 3️⃣  Persist the incoming user message.
        #      If an image was attached, prefix the text with a marker
        #      so the DB history knows an image was sent (without storing
        #      the heavy bytes).
        db_content = f"[Attached Image]\n{text}" if image_bytes else text
        await self._repo.add_message(
            conversation_id=conversation.id,
            role="user",
            content=db_content,
        )

        # 4️⃣  Fetch the conversation history from DB.
        #      This now includes the message we just saved.
        history = await self._repo.get_conversation_history(
            conversation_id=conversation.id,
        )

        # 5️⃣  Exclude the last user message from history so it is not
        #      duplicated — PromptBuilder.build_messages() appends the
        #      current user text as the final "user" turn automatically.
        if history and history[-1].role == "user":
            history = history[:-1]

        # 6️⃣  Retrieve the system instruction.
        system_prompt: str = self._builder.get_system_instruction()

        # 7️⃣  Build the Gemini-compatible contents payload.
        messages = self._builder.build_messages(
            system_prompt=system_prompt,
            history=history,
            current_user_message=text,
            image_bytes=image_bytes,
            mime_type=mime_type,
        )

        # 8️⃣  Call the AI model (with retries handled internally).
        try:
            ai_response_text: str = await self._ai.generate_response(messages)
        except AIException:
            logger.error(
                "AI service unavailable for user %d in conv %d",
                telegram_id,
                conversation.id,
            )
            return _AI_ERROR_REPLY

        # 9️⃣  Persist the AI's response.
        await self._repo.add_message(
            conversation_id=conversation.id,
            role="model",
            content=ai_response_text,
        )

        logger.info(
            "Processed message  ·  user=%d  ·  conv=%d  ·  reply_chars=%d",
            telegram_id,
            conversation.id,
            len(ai_response_text),
        )

        # 🔟  Return the response to the Telegram handler.
        return ai_response_text

    # ──────────────────────────────────────────
    #  Conversation reset
    # ──────────────────────────────────────────

    async def reset_conversation(self, telegram_id: int) -> bool:
        """Deactivate the user's current conversation so the next
        message starts a fresh one.

        Parameters
        ----------
        telegram_id:
            The Telegram user ID whose conversation should be reset.

        Returns
        -------
        bool
            ``True`` if an active conversation was found and
            deactivated; ``False`` if the user had no active
            conversation.
        """
        # Look up the user first.
        stmt = select(User).where(User.telegram_id == telegram_id)
        user: User | None = await self._session.scalar(stmt)

        if user is None:
            logger.warning(
                "reset_conversation called for unknown user %d",
                telegram_id,
            )
            return False

        # Find the active conversation.
        conv_stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user.id,
                Conversation.is_active.is_(True),
            )
            .limit(1)
        )
        conversation: Conversation | None = await self._session.scalar(conv_stmt)

        if conversation is None:
            logger.info(
                "No active conversation to reset for user %d",
                telegram_id,
            )
            return False

        # Deactivate the conversation.
        conversation.is_active = False
        await self._session.commit()

        logger.info(
            "Reset conversation  ·  user=%d  ·  conv=%d",
            telegram_id,
            conversation.id,
        )
        return True
