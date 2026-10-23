"""Product configuration and immutable offer read contracts."""

from dataclasses import dataclass
from uuid import UUID

from papilio_panel.shared.money import Currency


@dataclass(frozen=True)
class ProductDefinition:
    name: str
    core_id: UUID
    inbound_id: UUID
    price_minor: int
    currency: Currency = Currency.IRR
    user_level: int | None = None
    is_active: bool = True


@dataclass(frozen=True)
class ProductCreate:
    actor_id: int
    request_key: UUID
    definition: ProductDefinition


@dataclass(frozen=True)
class ProductChange:
    actor_id: int
    product_id: UUID
    expected_revision: int
    definition: ProductDefinition


@dataclass(frozen=True)
class ProductOfferRead:
    id: UUID
    product_id: UUID
    revision: int
    definition: ProductDefinition
    user_level: int


@dataclass(frozen=True)
class ProductRead:
    id: UUID
    owner_id: int
    offer: ProductOfferRead


@dataclass(frozen=True)
class ProductCreation:
    product: ProductRead
    original: ProductDefinition
    created: bool


@dataclass(frozen=True)
class ProductSearch:
    actor_id: int
    query: str = ""
    page: int = 1
    page_size: int = 20
    active_only: bool = False


@dataclass(frozen=True)
class ProductPage:
    items: tuple[ProductRead, ...]
    count: int
    page: int
    page_size: int
