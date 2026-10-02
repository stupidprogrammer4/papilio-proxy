from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from papilio_proxy.config.database import Base


class PaymentMethodModel(Base):
    __tablename__ = "payment_methods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(100))
    card_number: Mapped[str] = mapped_column(String(16))
    bank_name: Mapped[str] = mapped_column(String(100))
    account_holder: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class CardPaymentOrderModel(Base):
    """Immutable destination snapshot, unaffected by later card edits."""

    __tablename__ = "card_payment_orders"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True
    )
    method_id: Mapped[str] = mapped_column(String(36), ForeignKey("payment_methods.id"))
    method_title: Mapped[str] = mapped_column(String(100))
    card_number: Mapped[str] = mapped_column(String(16))
    bank_name: Mapped[str] = mapped_column(String(100))
    account_holder: Mapped[str] = mapped_column(String(100))


class PaymentReceiptModel(Base):
    __tablename__ = "payment_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("subscriptions.id"), index=True)
    image_ciphertext: Mapped[bytes] = mapped_column(LargeBinary(length=16_777_215), deferred=True)
    image_digest: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(String(300), default="")
    notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notice_leased_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ManualSettlementModel(Base):
    """Exactly one approved receipt and bank transaction can settle an order."""

    __tablename__ = "manual_settlements"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True
    )
    receipt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("payment_receipts.id"), unique=True
    )
    bank_reference: Mapped[str] = mapped_column(String(128), unique=True)
    amount_rial: Mapped[int] = mapped_column(BigInteger)
    approved_at: Mapped[datetime] = mapped_column(DateTime)
    approved_by: Mapped[str] = mapped_column(String(64))
