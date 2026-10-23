"""Owned invoice, metadata-only evidence and audit read models."""

from uuid import UUID

from django.core.paginator import EmptyPage, Paginator
from django.db.models import F, Q, QuerySet

from papilio_panel.shared.errors import Missing
from papilio_panel.shared.money import Currency

from ..domain import (
    DecisionAction,
    DecisionPage,
    DecisionRead,
    DecisionSearch,
    InvoicePage,
    InvoiceRead,
    InvoiceSearch,
    InvoiceState,
    PaymentDefinition,
    PaymentSettingsRead,
    ReceiptContent,
    ReceiptPage,
    ReceiptRead,
    ReceiptSearch,
)
from ..models import Invoice, PaymentDecision, PaymentSettings, Receipt


def settings_definition(row: PaymentSettings | Invoice) -> PaymentDefinition:
    return PaymentDefinition(
        row.recipient, row.destination, row.instructions, row.enabled, row.receipt_max_bytes
    )


def settings_read(row: PaymentSettings) -> PaymentSettingsRead:
    return PaymentSettingsRead(row.owner_id, row.revision, settings_definition(row))


def invoice_read(row: Invoice) -> InvoiceRead:
    return InvoiceRead(
        row.id,
        row.owner_id,
        row.request_key,
        row.customer_id,
        row.base_amount_minor,
        row.base_amount_minor,
        InvoiceState(row.status),
        row.revision,
        row.settings_revision,
        settings_definition(row),
        row.created_at,
        Currency(row.currency),
    )


def receipt_read(row: Receipt) -> ReceiptRead:
    return ReceiptRead(
        row.id,
        row.invoice_id,
        row.request_key,
        row.reference,
        row.note,
        row.filename,
        row.media_type,
        row.size_bytes,
        row.created_at,
    )


def receipt_content(row: Receipt) -> ReceiptContent | None:
    return (
        ReceiptContent(row.filename, row.media_type, bytes(row.content))
        if row.content is not None
        else None
    )


def decision_read(row: PaymentDecision) -> DecisionRead:
    return DecisionRead(
        row.id,
        row.invoice_id,
        row.actor_id,
        row.request_key,
        row.expected_revision,
        DecisionAction(row.action),
        row.reason,
        row.receipt_id,
        row.wallet_entry_id,
        row.created_at,
    )


def owned_invoices(actor_id: int) -> QuerySet[Invoice]:
    return Invoice.objects.filter(owner_id=actor_id, customer__owner_id=actor_id)


def owned_receipts(invoice_id: UUID, actor_id: int) -> QuerySet[Receipt]:
    return Receipt.objects.filter(
        invoice_id=invoice_id, invoice__owner_id=actor_id, invoice__customer__owner_id=actor_id
    )


def owned_decisions(invoice_id: UUID, actor_id: int) -> QuerySet[PaymentDecision]:
    return PaymentDecision.objects.filter(
        invoice_id=invoice_id,
        actor_id=actor_id,
        invoice__owner_id=actor_id,
        invoice__customer__owner_id=actor_id,
    ).filter(
        Q(receipt_id__isnull=True) | Q(receipt__invoice_id=F("invoice_id")),
        Q(wallet_entry_id__isnull=True)
        | Q(
            wallet_entry__wallet__customer_id=F("invoice__customer_id"),
            wallet_entry__actor_id=actor_id,
        ),
    )


class DjangoInvoiceReader:
    def read(self, invoice_id: UUID, actor_id: int) -> InvoiceRead:
        try:
            row = owned_invoices(actor_id).get(pk=invoice_id)
        except Invoice.DoesNotExist as error:
            raise Missing("The invoice was not found.") from error
        return invoice_read(row)

    def find_request(self, actor_id: int, request_key: UUID) -> InvoiceRead | None:
        row = owned_invoices(actor_id).filter(request_key=request_key).first()
        return invoice_read(row) if row is not None else None

    def search(self, values: InvoiceSearch) -> InvoicePage:
        rows = owned_invoices(values.actor_id).order_by("created_at", "id")
        if values.customer_id is not None:
            rows = rows.filter(customer_id=values.customer_id)
        if values.query:
            rows = rows.filter(
                Q(recipient__icontains=values.query)
                | Q(destination__icontains=values.query)
                | Q(customer__name__icontains=values.query)
            )
        if values.status is not None:
            rows = rows.filter(status=values.status)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The invoice page was not found.") from error
        return InvoicePage(
            tuple(invoice_read(row) for row in page), paginator.count, values.page, values.page_size
        )

    def read_receipt(self, receipt_id: UUID, invoice_id: UUID, actor_id: int) -> ReceiptRead:
        try:
            row = owned_receipts(invoice_id, actor_id).defer("content").get(pk=receipt_id)
        except Receipt.DoesNotExist as error:
            raise Missing("The receipt was not found on this invoice.") from error
        return receipt_read(row)

    def receipt_file(self, receipt_id: UUID, invoice_id: UUID, actor_id: int) -> ReceiptContent:
        try:
            row = owned_receipts(invoice_id, actor_id).get(pk=receipt_id)
        except Receipt.DoesNotExist as error:
            raise Missing("The receipt file was not found on this invoice.") from error
        result = receipt_content(row)
        if result is None:
            raise Missing("This receipt contains a payment reference without a file.")
        return result

    def receipts(self, values: ReceiptSearch) -> ReceiptPage:
        rows = (
            owned_receipts(values.invoice_id, values.actor_id)
            .defer("content")
            .order_by("created_at", "id")
        )
        if values.query:
            rows = rows.filter(
                Q(reference__icontains=values.query)
                | Q(note__icontains=values.query)
                | Q(filename__icontains=values.query)
            )
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The receipt page was not found.") from error
        return ReceiptPage(
            tuple(receipt_read(row) for row in page), paginator.count, values.page, values.page_size
        )

    def read_decision(self, decision_id: UUID, invoice_id: UUID, actor_id: int) -> DecisionRead:
        try:
            row = owned_decisions(invoice_id, actor_id).get(pk=decision_id)
        except PaymentDecision.DoesNotExist as error:
            raise Missing("The decision was not found on this invoice.") from error
        return decision_read(row)

    def decisions(self, values: DecisionSearch) -> DecisionPage:
        rows = owned_decisions(values.invoice_id, values.actor_id).order_by("created_at", "id")
        if values.query:
            rows = rows.filter(reason__icontains=values.query)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The decision page was not found.") from error
        return DecisionPage(
            tuple(decision_read(row) for row in page),
            paginator.count,
            values.page,
            values.page_size,
        )
