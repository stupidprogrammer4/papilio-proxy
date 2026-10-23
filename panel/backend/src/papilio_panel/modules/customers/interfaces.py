"""Customer application and persistence boundaries."""

from typing import Protocol
from uuid import UUID

from .domain import CustomerCreate, CustomerCreation, CustomerPage, CustomerRead, CustomerSearch


class CustomerStorage(Protocol):
    def create(self, values: CustomerCreate) -> CustomerCreation: ...
    def read(self, customer_id: UUID, actor_id: int) -> CustomerRead: ...
    def search(self, values: CustomerSearch) -> CustomerPage: ...


class CustomerCapability(CustomerStorage, Protocol):
    """All operations enforce the current operator's owner permission."""
