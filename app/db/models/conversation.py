"""
app/db/models/conversation.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQLAlchemy model for the ``conversations`` table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.message import Message
    from app.db.models.user import User


class Conversation(Base, TimestampMixin):
    """Represents a conversation thread between a user and the bot."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # ── Relationships ─────────────────────────
    user: Mapped[User] = relationship(
        "User",
        back_populates="conversations",
        lazy="selectin",
    )
    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} user_id={self.user_id} active={self.is_active}>"
