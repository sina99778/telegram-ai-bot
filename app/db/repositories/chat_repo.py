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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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

        Uses PostgreSQL ``INSERT ... ON CONFLICT DO UPDATE`` to make the
        entire operation a single atomic round-trip — eliminating the
        race-condition window that a SELECT→INSERT pattern exposes under
        high concurrency.

        On conflict (user already exists) only ``username`` and
        ``first_name`` are updated; default credits and other fields are
        preserved from the original INSERT.

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
        insert_values = dict(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            normal_credits=settings.DEFAULT_DAILY_NORMAL_CREDITS,
            credit_balance=settings.DEFAULT_DAILY_NORMAL_CREDITS,
            language="",
        )

        stmt = (
            pg_insert(User)
            .values(**insert_values)
            .on_conflict_do_update(
                index_elements=[User.telegram_id],
                set_=dict(
                    username=pg_insert(User).excluded.username,
                    first_name=pg_insert(User).excluded.first_name,
                ),
            )
            .returning(User)
        )

        result = await self._session.execute(stmt)
        user = result.scalar_one()
        await self._session.commit()

        logger.info(
            "Upserted user  ·  telegram_id=%d  ·  user_id=%d",
            telegram_id,
            user.id,
        )
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

    async def get_user_conversations(self, user_id: int, limit: int = 5) -> list[Conversation]:
        """Fetches the latest conversations for a user."""
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def set_active_conversation(self, telegram_id: int, conversation_id: int) -> bool:
        """Marks a specific conversation as the active one for the user."""
        from sqlalchemy import update
        user = await self.get_user_by_telegram_id(telegram_id)
        if not user:
            return False
            
        # First, deactivate all user's conversations
        await self._session.execute(
            update(Conversation)
            .where(Conversation.user_id == user.id)
            .values(is_active=False)
        )
        # Then, activate the selected one
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.user_id == user.id)
            .values(is_active=True)
        )
        # Commit will be handled by caller
        return True

    async def reset_active_conversation(self, telegram_id: int) -> bool:
        user = await self.get_user_by_telegram_id(telegram_id)
        if not user:
            return False

        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user.id,
                Conversation.is_active.is_(True),
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        conversation = await self._session.scalar(stmt)
        if conversation is None:
            return False

        conversation.is_active = False
        await self._session.commit()
        return True

    async def set_user_language(self, telegram_id: int, language: str) -> User | None:
        user = await self.get_user_by_telegram_id(telegram_id)
        if not user:
            return None
        user.language = language
        await self._session.commit()
        await self._session.refresh(user)
        return user

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

    # [DEPRECATED] deduct_image_credit and upgrade_to_vip removed. 
    # Use BillingService natively.

    async def ensure_daily_credits(self, telegram_id: int) -> User | None:
        """Lazy evaluation to ensure a daily minimum baseline for free usage."""
        user = await self.get_user_by_telegram_id(telegram_id)
        if not user:
            return None
        
        now = datetime.now(timezone.utc)
        # If last_credit_reset is None, or if the date has changed
        if not user.last_credit_reset or user.last_credit_reset.date() < now.date():
            # Free users receive a daily baseline in the normal wallet.
            if user.normal_credits < settings.DEFAULT_DAILY_NORMAL_CREDITS:
                deficit = settings.DEFAULT_DAILY_NORMAL_CREDITS - user.normal_credits
                from app.services.billing.billing_service import BillingService
                from app.core.enums import LedgerEntryType
                from app.core.enums import WalletType
                import time
                billing = BillingService(self._session)
                await billing.add_credits(
                    user_id=user.id,
                    amount=deficit,
                    entry_type=LedgerEntryType.BONUS,
                    reference_type="daily_reset",
                    reference_id=f"daily_reset_{user.id}_{int(time.time())}",
                    description="Daily login baseline top-up",
                    wallet_type=WalletType.NORMAL,
                )
            
            user.last_credit_reset = now
            user.sync_credit_balance()
            await self._session.commit()
        return user

    async def process_referral(self, invitee_id: int, referrer_id: int) -> bool:
        """Handle the referral logic: Reward referrer and invitee via BillingService."""
        if invitee_id == referrer_id:
            return False

        invitee = await self.get_user_by_telegram_id(invitee_id)
        referrer = await self.get_user_by_telegram_id(referrer_id)
        
        if invitee and referrer:
            if invitee.referred_by:
                return False

            from app.services.billing.billing_service import BillingService
            from app.core.enums import LedgerEntryType
            import time
            billing = BillingService(self._session)

            # Reward Invitee (25 credits)
            await billing.add_credits(
                user_id=invitee.id,
                amount=25,
                entry_type=LedgerEntryType.BONUS,
                reference_type="referral_invitee",
                reference_id=f"ref_in_{invitee.id}_{int(time.time())}",
                description=f"Referred by {referrer.telegram_id}"
            )
            invitee.referred_by = referrer.telegram_id
            
            # Reward Referrer (10 credits)
            await billing.add_credits(
                user_id=referrer.id,
                amount=10,
                entry_type=LedgerEntryType.BONUS,
                reference_type="referral_referrer",
                reference_id=f"ref_out_{referrer.id}_{invitee.id}_{int(time.time())}",
                description=f"Referred user {invitee.telegram_id}"
            )
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
