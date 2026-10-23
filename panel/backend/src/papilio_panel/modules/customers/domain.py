"""Customer identity inputs and authorized read shapes."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CustomerCreate:
    actor_id: int
    request_key: UUID
    name: str


@dataclass(frozen=True)
class CustomerRead:
    id: UUID
    owner_id: int
    name: str


@dataclass(frozen=True)
class CustomerCreation:
    customer: CustomerRead
    created: bool


@dataclass(frozen=True)
class CustomerSearch:
    actor_id: int
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class CustomerPage:
    items: tuple[CustomerRead, ...]
    count: int
    page: int
    page_size: int
