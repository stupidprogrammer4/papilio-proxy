"""Private immutable receipt intake coordinated with invoice state."""

from uuid import UUID

from django.db import transaction

from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import (
    InvoiceState,
    InvoiceTransition,
    ReceiptContent,
    ReceiptPage,
    ReceiptRead,
    ReceiptReservation,
    ReceiptSearch,
    ReceiptSubmit,
)
from ..interfaces import InvoiceCapability, InvoiceStorage
from .validation import receipt_input


class ReceiptEvidence:
    def __init__(
        self, storage: InvoiceStorage, invoices: InvoiceCapability, max_page_size: int
    ) -> None:
        self.storage = storage
        self.invoices = invoices
        self.max_page_size = max_page_size

    @transaction.atomic
    def submit(self, values: ReceiptSubmit) -> ReceiptReservation:
        invoice = self.invoices.read(values.invoice_id, values.actor_id)
        receipt_input(values, invoice.settings.receipt_max_bytes)
        result = self.storage.reserve_receipt(values)
        if result.original != values:
            raise Conflict("This receipt request key belongs to different evidence.")
        if result.created:
            self.storage.transition(
                InvoiceTransition(
                    values.actor_id, invoice.id, invoice.revision, InvoiceState.REVIEW
                )
            )
        return result

    def read(self, receipt_id: UUID, invoice_id: UUID, actor_id: int) -> ReceiptRead:
        self.invoices.read(invoice_id, actor_id)
        result = self.storage.read_receipt(receipt_id, invoice_id, actor_id)
        return result

    def file(self, receipt_id: UUID, invoice_id: UUID, actor_id: int) -> ReceiptContent:
        self.invoices.read(invoice_id, actor_id)
        result = self.storage.receipt_file(receipt_id, invoice_id, actor_id)
        return result

    def search(self, values: ReceiptSearch) -> ReceiptPage:
        self.invoices.read(values.invoice_id, values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= self.max_page_size:
            raise InvalidInput("Choose a positive page and supported page size.")
        result = self.storage.receipts(values)
        return result
