"""
app/db/repositories/chat_repo.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Data-Access Layer (Repository pattern) for the chat domain.

Provides async CRUD helpers for **User**, **Conversation**, and
**Message** entities using SQLAlchemy 2.0 async API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, User

logger = logging.getLogger(__name__)


class ChatRepository:
    """Encapsulates all database operations for the chat feature.

    Each instance is scoped to a single ``AsyncSession`` that the caller
    (typically a FastAPI dependency) is responsible for managing.

    Usage::

        async with async_session() as session:
            repo = ChatRepository(session)
            user = await repo.get_or_create_user(telegram_id=123456)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    # ──────────────────────────────────────────
    #  User Management
    # ──────────────────────────────────────────

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> User:
        """Return the ``User`` matching *telegram_id*, creating one if
        it does not already exist.

        Parameters
        ----------
        telegram_id:
            Unique Telegram user ID.
        username:
            Telegram ``@username`` (may be ``None``).
        first_name:
            Telegram first name (may be ``None``).

        Returns
        -------
        User
            The existing or newly-created user instance.
        """
        stmt = select(User).where(User.telegram_id == telegram_id)
        user: User | None = await self._session.scalar(stmt)

        if user is not None:
            # Optionally update mutable profile fields
            changed = False
            if username is not None and user.username != username:
                user.username = username
                changed = True
            if first_name is not None and user.first_name != first_name:
                user.first_name = first_name
                changed = True
            if changed:
                await self._session.commit()
                await self._session.refresh(user)
                logger.info("Updated profile for user %d", telegram_id)
            return user

        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
        )
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)

        logger.info("Created new user  ·  telegram_id=%d", telegram_id)
        return user

    # ──────────────────────────────────────────
    #  Conversation Management
    # ──────────────────────────────────────────

    async def get_or_create_active_conversation(
        self,
        user_id: int,
    ) -> Conversation:
        """Return the user's active conversation, creating one if none exists.

        An *active* conversation is one where ``is_active is True``.

        Parameters
        ----------
        user_id:
            The primary-key ID of the ``User`` (not the Telegram ID).

        Returns
        -------
        Conversation
            The active (or newly-created) conversation.
        """
        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.is_active.is_(True),
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        conversation: Conversation | None = await self._session.scalar(stmt)

        if conversation is not None:
            return conversation

        conversation = Conversation(
            user_id=user_id,
            is_active=True,
        )
        self._session.add(conversation)
        await self._session.commit()
        await self._session.refresh(conversation)

        logger.info(
            "Created new conversation  ·  user_id=%d  ·  conv_id=%d",
            user_id,
            conversation.id,
        )
        return conversation

    # ──────────────────────────────────────────
    #  Message Management
    # ──────────────────────────────────────────

    async def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
    ) -> Message:
        """Persist a new message in a conversation.

        Parameters
        ----------
        conversation_id:
            FK to the parent ``Conversation``.
        role:
            ``"user"`` or ``"model"``.
        content:
            The message body.

        Returns
        -------
        Message
            The newly-created message instance.
        """
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        self._session.add(message)
        await self._session.commit()
        await self._session.refresh(message)

        logger.debug(
            "Saved message  ·  conv_id=%d  ·  role=%s  ·  chars=%d",
            conversation_id,
            role,
            len(content),
        )
        return message

    # ──────────────────────────────────────────
    #  History Fetching
    # ──────────────────────────────────────────

    async def get_conversation_history(
        self,
        conversation_id: int,
        limit: int = 20,
    ) -> list[Message]:
        """Return the most recent messages for a conversation, ordered
        chronologically (oldest → newest).

        Parameters
        ----------
        conversation_id:
            FK to the target ``Conversation``.
        limit:
            Maximum number of messages to return (newest are kept).

        Returns
        -------
        list[Message]
            Messages sorted by ``created_at ASC``.
        """
        # Sub-select the newest *limit* rows, then re-order ASC
        # so the caller gets a natural chronological list.
        inner = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
            .subquery()
        )

        stmt = (
            select(Message)
            .join(inner, Message.id == inner.c.id)
            .order_by(Message.created_at.asc())
        )

        result = await self._session.execute(stmt)
        messages: list[Message] = list(result.scalars().all())

        logger.debug(
            "Fetched history  ·  conv_id=%d  ·  count=%d",
            conversation_id,
            len(messages),
        )
        return messages

    # ──────────────────────────────────────────
    #  Statistics
    # ──────────────────────────────────────────

    async def get_bot_stats(self) -> dict[str, int]:
        """Fetch total counts of users, conversations, and messages."""
        users_count = await self._session.scalar(select(func.count(User.id))) or 0
        conv_count = await self._session.scalar(select(func.count(Conversation.id))) or 0
        msg_count = await self._session.scalar(select(func.count(Message.id))) or 0
        
        return {
            "users": users_count,
            "conversations": conv_count,
            "messages": msg_count
        }

    # ──────────────────────────────────────────
    #  User Lookup & VIP Management
    # ──────────────────────────────────────────

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        """Fetch a user by their Telegram ID."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        return await self._session.scalar(stmt)

    async def deduct_image_credit(self, telegram_id: int) -> bool:
        """Deduct one image credit if the user has enough. Returns True if successful."""
        user = await self.get_user_by_telegram_id(telegram_id)
        if user and user.premium_credits > 0:
            user.premium_credits -= 1
            await self._session.commit()
            return True
        return False

    async def upgrade_to_vip(self, telegram_id: int, add_credits: int, expire_date: datetime | None = None) -> bool:
        """Upgrade a user to VIP status and add credits."""
        user = await self.get_user_by_telegram_id(telegram_id)
        if user:
            user.is_vip = True
            user.premium_credits += add_credits
            if expire_date:
                user.vip_expire_date = expire_date
            await self._session.commit()
            return True
        return False

    async def ensure_daily_credits(self, telegram_id: int) -> User | None:
        """Lazy evaluation to reset daily credits if a new day has started."""
        user = await self.get_user_by_telegram_id(telegram_id)
        if not user:
            return None
        
        now = datetime.now(timezone.utc)
        # If last_credit_reset is None, or if the date has changed
        if not user.last_credit_reset or user.last_credit_reset.date() < now.date():
            user.normal_credits = 50
            # Top up premium credits to at least 10, keeping any extra referral bonuses
            user.premium_credits = max(10, user.premium_credits)
            user.last_credit_reset = now
            await self._session.commit()
        return user

    async def process_referral(self, invitee_id: int, referrer_id: int) -> bool:
        """Handle the referral logic: Reward referrer and invitee."""
        if invitee_id == referrer_id:
            return False

        invitee = await self.get_user_by_telegram_id(invitee_id)
        referrer = await self.get_user_by_telegram_id(referrer_id)
        
        if invitee and referrer:
            if invitee.referred_by:
                return False

            # Reward both
            invitee.premium_credits += 25
            invitee.referred_by = referrer.telegram_id
            
            # --- NEW REFERRAL RULES ---
            referrer.premium_credits += 10
            referrer.total_invites += 1
            
            # Special 10-invite threshold check
            if referrer.total_invites == 10:
                referrer.special_reward_images_left += 5
                from datetime import datetime, timezone, timedelta
                referrer.special_reward_expire = datetime.now(timezone.utc) + timedelta(weeks=1)

            await self._session.commit()
            return True
        return False

    async def get_total_users_count(self) -> int:
        """Returns the total number of registered users."""
        result = await self._session.execute(select(func.count(User.id)))
        return result.scalar() or 0

    async def get_users_paginated(self, limit: int = 10, offset: int = 0) -> list[User]:
        """Fetches a paginated list of users ordered by newest first."""
        result = await self._session.execute(
            select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def get_all_users(self) -> list[User]:
        """Fetch all users from the database for broadcasting."""
        stmt = select(User)
        result = await self._session.scalars(stmt)
        return list(result.all())
