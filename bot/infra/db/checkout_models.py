from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.infra.db.models import Base


class CheckoutSettingsModel(Base):
    __tablename__ = "checkout_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    shop_id: Mapped[str] = mapped_column(String(36), default="")
    card_id: Mapped[str] = mapped_column(String(36), default="")
    callback_url: Mapped[str] = mapped_column(String(2048), default="")


class CheckoutReservationModel(Base):
    """A durable claim prevents duplicate creation after a provider timeout/crash."""
    __tablename__ = "checkout_reservations"
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True
    )
