"""Issue manual invoices with frozen destination and exact base credit terms."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.customers.interfaces import CustomerCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.wallets.interfaces import WalletCapability
from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import InvoiceCreation, InvoiceIssue, InvoicePage, InvoiceRead, InvoiceSearch
from ..interfaces import InvoiceStorage, PaymentSettingsCapability
from .validation import invoice_amount, matching_invoice


class InvoiceAccounts:
    def __init__(
        self,
        storage: InvoiceStorage,
        access: AdminAccessCapability,
        customers: CustomerCapability,
        wallets: WalletCapability,
        settings: PaymentSettingsCapability,
        max_page_size: int,
    ) -> None:
        self.storage = storage
        self.access = access
        self.customers = customers
        self.wallets = wallets
        self.settings = settings
        self.max_page_size = max_page_size

    @transaction.atomic
    def issue(self, values: InvoiceIssue) -> InvoiceCreation:
        self.access.authorize_owner(values.actor_id)
        invoice_amount(values.base_amount_minor)
        self.customers.read(values.customer_id, values.actor_id)
        prior = self.storage.find_request(values.actor_id, values.request_key)
        if prior is not None:
            matching_invoice(prior, values)
            return InvoiceCreation(prior, False)
        self.wallets.read(values.customer_id, values.actor_id)
        settings = self.settings.read(values.actor_id)
        if not settings.definition.enabled:
            raise Conflict("New manual payment invoices are disabled.")
        result = self.storage.create(values, settings)
        matching_invoice(result.invoice, values)
        return result

    def read(self, invoice_id: UUID, actor_id: int) -> InvoiceRead:
        self.access.authorize_owner(actor_id)
        result = self.storage.read(invoice_id, actor_id)
        return result

    def search(self, values: InvoiceSearch) -> InvoicePage:
        self.access.authorize_owner(values.actor_id)
        if values.customer_id is not None:
            self.customers.read(values.customer_id, values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= self.max_page_size:
            raise InvalidInput("Choose a positive page and supported page size.")
        result = self.storage.search(values)
        return result
