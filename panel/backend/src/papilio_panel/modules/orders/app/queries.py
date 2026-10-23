"""Resolve accepted order records within authoritative owner/customer context."""

from uuid import UUID

from papilio_panel.modules.customers.interfaces import CustomerCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import InvalidInput

from ..domain import OrderPage, OrderRead, OrderSearch
from ..interfaces import OrderStorage


class OrderQueries:
    def __init__(
        self,
        storage: OrderStorage,
        access: AdminAccessCapability,
        customers: CustomerCapability,
        max_page_size: int,
    ) -> None:
        self.storage = storage
        self.access = access
        self.customers = customers
        self.max_page_size = max_page_size

    def read(self, order_id: UUID, actor_id: int) -> OrderRead:
        self.access.authorize_owner(actor_id)
        result = self.storage.read(order_id, actor_id)
        self.customers.read(result.customer_id, actor_id)
        return result

    def search(self, values: OrderSearch) -> OrderPage:
        self.access.authorize_owner(values.actor_id)
        if values.customer_id is not None:
            self.customers.read(values.customer_id, values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= self.max_page_size:
            raise InvalidInput("Choose a positive page and a supported page size.")
        result = self.storage.search(values)
        return result
