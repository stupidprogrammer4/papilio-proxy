from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from papilio_proxy.config.database import Base

if TYPE_CHECKING:
    from papilio_proxy.modules.accounts.users.infra.tables import UserModel


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


class PlanVisualModel(Base):
    """Per-plan visual settings, added without altering the existing plans table."""

    __tablename__ = "plan_visuals"

    plan_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("plans.code", ondelete="CASCADE"), primary_key=True
    )
    emoji: Mapped[str] = mapped_column(String(32))


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


class SubscriptionTermsModel(Base):
    """Immutable purchased duration, unaffected by later catalog edits."""

    __tablename__ = "subscription_terms"

    subscription_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True
    )
    duration_days: Mapped[int] = mapped_column(Integer)
