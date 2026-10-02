from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from papilio_proxy.config.database import Base


class PricingAssumptionsModel(Base):
    """Editable owner-supplied cost assumptions, with explicit currency and units."""

    __tablename__ = "pricing_assumptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_days: Mapped[int] = mapped_column(Integer)
    daily_server_cost_rial: Mapped[int] = mapped_column(BigInteger)
    included_traffic_gb: Mapped[int] = mapped_column(Integer)
    overage_cost_rial_per_gb: Mapped[int] = mapped_column(BigInteger)
    target_customers: Mapped[int] = mapped_column(Integer)
    contingency_basis_points: Mapped[int] = mapped_column(Integer)
    target_margin_basis_points: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
