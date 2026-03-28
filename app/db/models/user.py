from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # Subscription fields
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vip_expire_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
