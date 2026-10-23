"""Exact wallet inputs, journal facts and native balance update bounds."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.shared.money import Currency, MoneyUnit


class EntryKind(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


@dataclass(frozen=True)
class WalletOpen:
    actor_id: int
    customer_id: UUID
    currency: Currency
    credit_limit_minor: int = 0


@dataclass(frozen=True)
class WalletRead:
    id: UUID
    customer_id: UUID
    currency: Currency
    balance_minor: int
    credit_limit_minor: int
    revision: int
    unit: MoneyUnit = MoneyUnit.RIAL


@dataclass(frozen=True)
class WalletOpening:
    wallet: WalletRead
    created: bool


@dataclass(frozen=True)
class WalletChange:
    actor_id: int
    customer_id: UUID
    expected_revision: int
    credit_limit_minor: int


@dataclass(frozen=True)
class JournalInput:
    request_key: UUID
    kind: EntryKind
    amount_minor: int
    reason: str


@dataclass(frozen=True)
class WalletPost:
    actor_id: int
    customer_id: UUID
    entry: JournalInput


@dataclass(frozen=True)
class JournalReservation:
    id: UUID
    original: JournalInput
    created: bool


@dataclass(frozen=True)
class BalanceChange:
    wallet_id: UUID
    customer_id: UUID
    expected_revision: int
    delta_minor: int
    minimum_before_minor: int
    maximum_before_minor: int


@dataclass(frozen=True)
class BalanceObservation:
    before_minor: int
    after_minor: int


@dataclass(frozen=True)
class JournalEntryRead:
    id: UUID
    wallet_id: UUID
    request_key: UUID
    kind: EntryKind
    amount_minor: int
    reason: str
    balance_before_minor: int
    balance_after_minor: int
    created_at: datetime
    currency: Currency
    actor_id: int
    unit: MoneyUnit = MoneyUnit.RIAL


@dataclass(frozen=True)
class JournalEntryCreation:
    entry: JournalEntryRead
    created: bool


@dataclass(frozen=True)
class JournalSearch:
    actor_id: int
    customer_id: UUID
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class JournalPage:
    items: tuple[JournalEntryRead, ...]
    count: int
    page: int
    page_size: int
