from datetime import datetime, timezone
from typing import Optional, Any, List
from sqlalchemy import BigInteger, String, Float, Boolean, Text, CheckConstraint, Index, Enum as SQLEnum, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.core.enums import TransactionStatus, LedgerEntryType, FeatureName, MessageRole

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint('credit_balance >= 0', name='check_credit_balance_positive'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    
    credit_balance: Mapped[int] = mapped_column(default=0)
    lifetime_credits_purchased: Mapped[int] = mapped_column(default=0)
    lifetime_credits_used: Mapped[int] = mapped_column(default=0)
    
    subscription_plan: Mapped[Optional[str]] = mapped_column(String(50))
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_premium: Mapped[bool] = mapped_column(default=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    ledgers: Mapped[List["CreditLedger"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    payments: Mapped[List["PaymentTransaction"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")

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
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB) 
    
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
