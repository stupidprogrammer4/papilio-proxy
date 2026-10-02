from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PaymentError(ValueError):
    """A payment action cannot be completed in its current state."""


class PaymentKind(StrEnum):
    CARD_TO_CARD = "card_to_card"


class ReceiptStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PaymentMethod:
    id: str
    kind: PaymentKind
    title: str
    card_number: str
    bank_name: str
    account_holder: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class PaymentInstructions:
    order_id: str
    amount_rial: int
    plan_title: str
    method_title: str
    card_number: str
    bank_name: str
    account_holder: str


@dataclass(frozen=True, slots=True)
class PaymentReceipt:
    id: str
    order_id: str
    telegram_id: int
    customer_name: str
    plan_title: str
    amount_rial: int
    status: ReceiptStatus
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    rejection_reason: str
    bank_reference: str | None
    card_number: str
    bank_name: str
    account_holder: str


@dataclass(frozen=True, slots=True)
class ReceiptNotification:
    receipt_id: str
    order_id: str
    telegram_id: int
    status: ReceiptStatus
    reason: str
