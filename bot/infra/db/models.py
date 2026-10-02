from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata for the MySQL schema."""


class UserModel(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    subscriptions: Mapped[list[SubscriptionModel]] = relationship(back_populates="user")


class PlanModel(Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    traffic_gb: Mapped[int] = mapped_column(Integer)
    duration_days: Mapped[int] = mapped_column(Integer)
    price_rial: Mapped[int] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class UserAccessPolicyModel(Base):
    __tablename__ = "user_access_policies"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), primary_key=True
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(300), default="")
    changed_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class PlanVisualModel(Base):
    """Per-plan visual settings, added without altering the existing plans table."""

    __tablename__ = "plan_visuals"

    plan_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("plans.code", ondelete="CASCADE"), primary_key=True
    )
    emoji: Mapped[str] = mapped_column(String(32))


class PaymentAttemptModel(Base):
    """A KPay transaction is bound to exactly one immutable order snapshot."""

    __tablename__ = "payment_attempts"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True
    )
    authority: Mapped[str] = mapped_column(String(256), unique=True)
    provider_transaction_id: Mapped[str] = mapped_column(String(128), unique=True)
    amount_rial: Mapped[int] = mapped_column(BigInteger)
    payment_url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class BotBrandingModel(Base):
    __tablename__ = "bot_branding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    short_description: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class EncryptedCredentialModel(Base):
    __tablename__ = "encrypted_credentials"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(String(4096))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class SubscriptionModel(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"), index=True)
    plan_code: Mapped[str] = mapped_column(String(64))
    protocol: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    traffic_limit_bytes: Mapped[int] = mapped_column(BigInteger)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    price_rial: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[UserModel] = relationship(back_populates="subscriptions")


class SubscriptionAccessModel(Base):
    """Encrypted bearer token and node-issued links for one paid entitlement."""

    __tablename__ = "subscription_access"

    subscription_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    token_ciphertext: Mapped[str] = mapped_column(Text)
    vless_ciphertext: Mapped[str] = mapped_column(Text)
    vmess_ciphertext: Mapped[str] = mapped_column(Text)
    uplink_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    downlink_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_measured_at: Mapped[datetime] = mapped_column(DateTime)


class ProvisionDeliveryModel(Base):
    """Durable delivery notice; sending can retry without reprovisioning."""

    __tablename__ = "provision_deliveries"

    subscription_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SubscriptionTermsModel(Base):
    """Immutable purchased duration, unaffected by later catalog edits."""

    __tablename__ = "subscription_terms"

    subscription_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True
    )
    duration_days: Mapped[int] = mapped_column(Integer)


class UsageAlertModel(Base):
    """At-least-once Telegram warning with a durable, retryable claim."""

    __tablename__ = "usage_alerts"
    __table_args__ = (UniqueConstraint("subscription_id", "kind"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(String(36), ForeignKey("subscriptions.id"))
    kind: Mapped[str] = mapped_column(String(32))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
