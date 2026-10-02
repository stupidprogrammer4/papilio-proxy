from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from papilio_proxy.config.database import Base


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


class UsageAlertModel(Base):
    """At-least-once Telegram warning with a durable, retryable claim."""

    __tablename__ = "usage_alerts"
    __table_args__ = (UniqueConstraint("subscription_id", "kind"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(String(36), ForeignKey("subscriptions.id"))
    kind: Mapped[str] = mapped_column(String(32))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
