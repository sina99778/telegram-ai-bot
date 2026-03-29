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
    
    # VIP & Ban
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vip_expire_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Credits System
    normal_credits: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    premium_credits: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    last_credit_reset: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # NEW FIELD: Stores user's preferred model ('flash' or 'pro')
    preferred_text_model: Mapped[str] = mapped_column(String, default='flash')
    language: Mapped[str] = mapped_column(String(2), default="fa")

    # Referral System
    referral_code: Mapped[str | None] = mapped_column(String(50), unique=True, index=True, nullable=True)
    referred_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_invites: Mapped[int] = mapped_column(Integer, default=0)
    special_reward_images_left: Mapped[int] = mapped_column(Integer, default=0)
    special_reward_expire: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")

class PromoCode(Base):
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    vip_days: Mapped[int] = mapped_column(Integer, default=0)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class UserPromo(Base):
    __tablename__ = "user_promos"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    promo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
