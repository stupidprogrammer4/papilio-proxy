"""Register and resolve accounts through authoritative operator permissions."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import CustomerCreate, CustomerCreation, CustomerPage, CustomerRead, CustomerSearch
from ..interfaces import CustomerStorage


class CustomerAccounts:
    def __init__(
        self, storage: CustomerStorage, access: AdminAccessCapability, max_page_size: int
    ) -> None:
        self.storage = storage
        self.access = access
        self.max_page_size = max_page_size

    @transaction.atomic
    def create(self, values: CustomerCreate) -> CustomerCreation:
        self.access.authorize_owner(values.actor_id)
        if not values.name.strip() or values.name != values.name.strip() or len(values.name) > 80:
            raise InvalidInput("Enter a customer name without surrounding whitespace.")
        result = self.storage.create(values)
        if result.customer.name != values.name:
            raise Conflict("This request key belongs to a different customer.")
        return result

    def read(self, customer_id: UUID, actor_id: int) -> CustomerRead:
        self.access.authorize_owner(actor_id)
        customer = self.storage.read(customer_id, actor_id)
        return customer

    def search(self, values: CustomerSearch) -> CustomerPage:
        self.access.authorize_owner(values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= self.max_page_size:
            raise InvalidInput("Choose a positive page and a supported page size.")
        page = self.storage.search(values)
        return page
