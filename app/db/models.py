from datetime import datetime, timezone
from typing import Optional, Any, List
from sqlalchemy import BigInteger, String, Float, Boolean, Text, CheckConstraint, Index, Enum as SQLEnum, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.core.enums import (
    TransactionStatus,
    LedgerEntryType,
    FeatureName,
    MessageRole,
    WalletType,
    PromoCodeKind,
)

class Base(DeclarativeBase):
    pass

class User(Base):
    """Telegram bot user with dual-wallet billing and VIP access control.

    Accounting Model
    ----------------
    ``normal_credits`` / ``vip_credits``
        The authoritative spendable wallets.

    ``credit_balance``
        Backward-compatible aggregate of both wallets for reporting and
        legacy read paths. New write paths should not mutate it directly.

    ``lifetime_credits_purchased`` / ``lifetime_credits_used``
        Monotonically increasing counters for analytics.  They are
        updated atomically alongside the wallet fields inside
        ``BillingService.deduct_credits`` / ``add_credits``.

    Ledger Invariant
        Every wallet mutation produces a corresponding
        :class:`CreditLedger` row.  The sum of all ledger ``amount``
        values for a wallet should equal that wallet's mutations.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint('credit_balance >= 0', name='check_credit_balance_positive'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_name: Mapped[Optional[str]] = mapped_column(String(255))
    
    # ── Billing (authoritative) ───────────────
    credit_balance: Mapped[int] = mapped_column(default=0)
    lifetime_credits_purchased: Mapped[int] = mapped_column(default=0)
    lifetime_credits_used: Mapped[int] = mapped_column(default=0)
    
    # ── DEPRECATED legacy credit fields ───────
    # These columns are retained only for schema compatibility.
    # Do NOT read or write them in new code — use credit_balance
    # via BillingService instead.
    normal_credits: Mapped[int] = mapped_column(default=50)
    vip_credits: Mapped[int] = mapped_column(default=0)
    last_credit_reset: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # ── Subscription / VIP ────────────────────
    subscription_plan: Mapped[Optional[str]] = mapped_column(String(50))
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_premium: Mapped[bool] = mapped_column(default=False)
    is_vip: Mapped[bool] = mapped_column(default=False)
    vip_expire_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # ── Referral system ───────────────────────
    referred_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_invites: Mapped[int] = mapped_column(default=0)
    special_reward_images_left: Mapped[int] = mapped_column(default=0)
    special_reward_expire: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # ── User preferences ───────────────────────
    language: Mapped[str] = mapped_column(String(10), default="fa")
    preferred_text_model: Mapped[Optional[str]] = mapped_column(String(50))
    keep_chat_history: Mapped[bool] = mapped_column(default=True)
    
    # ── Admin / moderation ────────────────────
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_banned: Mapped[bool] = mapped_column(default=False)
    
    # ── Timestamps ────────────────────────────
    last_daily_reward: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    ledgers: Mapped[List["CreditLedger"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    payments: Mapped[List["PaymentTransaction"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def premium_credits(self) -> int:
        """Backward-compatible alias for legacy code paths."""
        return self.vip_credits

    @premium_credits.setter
    def premium_credits(self, value: int) -> None:
        self.vip_credits = value

    @property
    def has_active_vip(self) -> bool:
        if not self.is_vip:
            return False
        if self.vip_expire_date is None:
            return True
        return self.vip_expire_date > datetime.now(timezone.utc)

    def sync_credit_balance(self) -> None:
        self.credit_balance = max(0, self.normal_credits) + max(0, self.vip_credits)

class CreditLedger(Base):
    __tablename__ = "credit_ledger"
    __table_args__ = (
        UniqueConstraint('user_id', 'reference_type', 'reference_id', name='uq_ledger_reference'),
        Index('ix_credit_ledger_user_created', 'user_id', 'created_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[LedgerEntryType] = mapped_column(SQLEnum(LedgerEntryType))
    
    # Amount convention: negative = usage, positive = purchase/refund/bonus
    amount: Mapped[int] = mapped_column() 
    balance_before: Mapped[int] = mapped_column()
    balance_after: Mapped[int] = mapped_column()
    wallet_type: Mapped[WalletType] = mapped_column(SQLEnum(WalletType), default=WalletType.NORMAL)
    
    reference_type: Mapped[Optional[str]] = mapped_column(String(50)) 
    reference_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="ledgers")

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        Index('ix_payment_transactions_status', 'status'),
        UniqueConstraint('provider', 'provider_payment_id', name='uq_payment_provider_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50)) 
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10))
    credits_granted: Mapped[int] = mapped_column()
    status: Mapped[TransactionStatus] = mapped_column(SQLEnum(TransactionStatus), default=TransactionStatus.PENDING)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True) 
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON().with_variant(JSONB, "postgresql")) 
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship(back_populates="payments")

class FeatureConfig(Base):
    __tablename__ = "feature_configs"

    name: Mapped[FeatureName] = mapped_column(SQLEnum(FeatureName), primary_key=True)
    credit_cost: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    cooldown_seconds: Mapped[Optional[int]] = mapped_column()
    max_input_tokens: Mapped[Optional[int]] = mapped_column()
    max_output_tokens: Mapped[Optional[int]] = mapped_column()
    fallback_model_name: Mapped[Optional[str]] = mapped_column(String(100))
    daily_limit: Mapped[Optional[int]] = mapped_column() 
    plan_required: Mapped[Optional[str]] = mapped_column(String(50)) 
    provider: Mapped[str] = mapped_column(String(50), default="antigravity")
    model_name: Mapped[str] = mapped_column(String(100)) 
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    conversation_mode: Mapped[str] = mapped_column(String(50), default="flash") 
    persona: Mapped[str] = mapped_column(String(50), default="default_assistant")
    language_preference: Mapped[str] = mapped_column(String(10), default="en")
    last_model_used: Mapped[Optional[str]] = mapped_column(String(100))
    total_tokens_used: Mapped[int] = mapped_column(default=0)
    summary_version: Mapped[int] = mapped_column(default=0)
    summary_text: Mapped[Optional[str]] = mapped_column(Text) 
    summarization_pending: Mapped[bool] = mapped_column(default=False)
    summarization_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    summarization_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_summary_job_id: Mapped[Optional[str]] = mapped_column(String(255))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[MessageRole] = mapped_column(SQLEnum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    tokens_used: Mapped[Optional[int]] = mapped_column()
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    kind: Mapped[PromoCodeKind] = mapped_column(SQLEnum(PromoCodeKind), default=PromoCodeKind.GIFT_NORMAL_CREDITS)
    normal_credits: Mapped[int] = mapped_column(default=0)
    vip_credits: Mapped[int] = mapped_column(default=0)
    vip_days: Mapped[int] = mapped_column(default=0)
    discount_percent: Mapped[int] = mapped_column(default=0)
    max_uses: Mapped[int] = mapped_column(default=1)
    used_count: Mapped[int] = mapped_column(default=0)
    max_uses_per_user: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @property
    def credits(self) -> int:
        """Backward-compatible alias used by older redemption code."""
        return self.normal_credits

class UserPromo(Base):
    __tablename__ = "user_promos"
    __table_args__ = (
        UniqueConstraint('user_id', 'promo_id', name='uq_user_promo'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), index=True)
    used_count: Mapped[int] = mapped_column(default=0)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
