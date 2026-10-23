"""Issued manual payment terms, private evidence and audited decisions."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.shared.money import Currency, MoneyUnit

DEFAULT_INVOICE_ISSUANCE_ENABLED = True
DEFAULT_RECEIPT_MAX_BYTES = 4194304
MAX_RECEIPT_BYTES = 1073741823


class InvoiceState(StrEnum):
    OPEN = "open"
    REVIEW = "review"
    REJECTED = "rejected"
    SETTLED = "settled"


class DecisionAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class PaymentDefinition:
    recipient: str
    destination: str
    instructions: str = ""
    enabled: bool = DEFAULT_INVOICE_ISSUANCE_ENABLED
    receipt_max_bytes: int = DEFAULT_RECEIPT_MAX_BYTES


@dataclass(frozen=True)
class PaymentSettingsRead:
    owner_id: int
    revision: int
    definition: PaymentDefinition


@dataclass(frozen=True)
class PaymentSettingsCreate:
    actor_id: int
    definition: PaymentDefinition


@dataclass(frozen=True)
class PaymentSettingsChange:
    actor_id: int
    expected_revision: int
    definition: PaymentDefinition


@dataclass(frozen=True)
class InvoiceIssue:
    actor_id: int
    request_key: UUID
    customer_id: UUID
    base_amount_minor: int


@dataclass(frozen=True)
class InvoiceRead:
    id: UUID
    owner_id: int
    request_key: UUID
    customer_id: UUID
    base_amount_minor: int
    amount_due_minor: int
    status: InvoiceState
    revision: int
    settings_revision: int
    settings: PaymentDefinition
    created_at: datetime
    currency: Currency = Currency.IRR
    unit: MoneyUnit = MoneyUnit.RIAL
    mode: str = "manual"


@dataclass(frozen=True)
class InvoiceCreation:
    invoice: InvoiceRead
    created: bool


@dataclass(frozen=True)
class InvoiceSearch:
    actor_id: int
    customer_id: UUID | None = None
    status: InvoiceState | None = None
    page: int = 1
    page_size: int = 20
    query: str = ""


@dataclass(frozen=True)
class InvoicePage:
    items: tuple[InvoiceRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class ReceiptContent:
    filename: str
    media_type: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class ReceiptSubmit:
    actor_id: int
    invoice_id: UUID
    request_key: UUID
    reference: str
    note: str
    file: ReceiptContent | None = None


@dataclass(frozen=True)
class ReceiptRead:
    id: UUID
    invoice_id: UUID
    request_key: UUID
    reference: str
    note: str
    filename: str
    media_type: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True)
class ReceiptReservation:
    receipt: ReceiptRead
    original: ReceiptSubmit
    created: bool


@dataclass(frozen=True)
class ReceiptSearch:
    actor_id: int
    invoice_id: UUID
    page: int = 1
    page_size: int = 20
    query: str = ""


@dataclass(frozen=True)
class DecisionSearch:
    actor_id: int
    invoice_id: UUID
    page: int = 1
    page_size: int = 20
    query: str = ""


@dataclass(frozen=True)
class ReceiptPage:
    items: tuple[ReceiptRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class DecisionInput:
    actor_id: int
    invoice_id: UUID
    request_key: UUID
    expected_revision: int
    action: DecisionAction
    reason: str
    receipt_id: UUID | None = None


@dataclass(frozen=True)
class DecisionRead:
    id: UUID
    invoice_id: UUID
    actor_id: int
    request_key: UUID
    expected_revision: int
    action: DecisionAction
    reason: str
    receipt_id: UUID | None
    wallet_entry_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class DecisionReservation:
    decision: DecisionRead
    original: DecisionInput
    created: bool


@dataclass(frozen=True)
class DecisionResult:
    invoice: InvoiceRead
    decision: DecisionRead
    created: bool


@dataclass(frozen=True)
class DecisionPage:
    items: tuple[DecisionRead, ...]
    count: int
    page: int
    page_size: int


class PaymentEventOutcome(StrEnum):
    QUEUED = "queued"
    NO_CONVERSATION = "no_conversation"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class PaymentEventRead:
    id: UUID
    decision_id: UUID
    invoice_id: UUID
    owner_id: int
    action: DecisionAction
    created_at: datetime
    processed_at: datetime | None
    outcome: PaymentEventOutcome | None


@dataclass(frozen=True)
class PaymentEventDelivery:
    id: UUID
    owner_id: int


@dataclass(frozen=True)
class InvoiceTransition:
    actor_id: int
    invoice_id: UUID
    expected_revision: int
    status: InvoiceState
