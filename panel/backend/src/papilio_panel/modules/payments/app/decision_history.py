"""Query the authorized invoice decision history without financial write dependencies."""

from papilio_panel.shared.errors import InvalidInput

from ..domain import DecisionPage, DecisionSearch
from ..interfaces import InvoiceCapability, InvoiceStorage


class PaymentDecisionHistory:
    def __init__(
        self, storage: InvoiceStorage, invoices: InvoiceCapability, max_page_size: int
    ) -> None:
        self.storage = storage
        self.invoices = invoices
        self.max_page_size = max_page_size

    def search(self, values: DecisionSearch) -> DecisionPage:
        self.invoices.read(values.invoice_id, values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= self.max_page_size:
            raise InvalidInput("Choose a positive page and supported page size.")
        result = self.storage.decisions(values)
        return result
