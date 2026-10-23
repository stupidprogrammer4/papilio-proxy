"""Purchase inputs and immutable accepted terms owned by each order."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.shared.money import Currency, MoneyUnit


class OrderState(StrEnum):
    PENDING = "pending"
    PURCHASED = "purchased"


@dataclass(frozen=True)
class PurchaseDefinition:
    customer_id: UUID
    product_id: UUID
    expected_revision: int
    service_name: str


@dataclass(frozen=True)
class PurchaseInput:
    actor_id: int
    request_key: UUID
    definition: PurchaseDefinition


@dataclass(frozen=True)
class PurchaseTerms:
    product_id: UUID
    offer_id: UUID
    offer_revision: int
    product_name: str
    price_minor: int
    currency: Currency
    core_id: UUID
    inbound_id: UUID
    user_level: int
    unit: MoneyUnit = MoneyUnit.RIAL


@dataclass(frozen=True)
class OrderRead:
    id: UUID
    owner_id: int
    customer_id: UUID
    terms: PurchaseTerms
    service_name: str
    status: OrderState
    service_id: UUID | None
    wallet_entry_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class OrderCreation:
    order: OrderRead
    created: bool


@dataclass(frozen=True)
class OrderSearch:
    actor_id: int
    customer_id: UUID | None = None
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class OrderPage:
    items: tuple[OrderRead, ...]
    count: int
    page: int
    page_size: int
