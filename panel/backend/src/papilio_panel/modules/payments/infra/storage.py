"""Native invoice reservations and conditional aggregate transitions."""

from uuid import UUID

from django.db.models import F

from papilio_panel.shared.errors import Conflict
from papilio_panel.shared.money import MAX_MONEY_MINOR

from ..domain import (
    DecisionAction,
    DecisionInput,
    DecisionReservation,
    InvoiceCreation,
    InvoiceIssue,
    InvoiceState,
    InvoiceTransition,
    PaymentSettingsRead,
    ReceiptReservation,
    ReceiptSubmit,
)
from ..models import Invoice, PaymentDecision, Receipt
from .readers import DjangoInvoiceReader, decision_read, invoice_read, receipt_content, receipt_read


class DjangoInvoiceStorage(DjangoInvoiceReader):
    def create(self, values: InvoiceIssue, settings: PaymentSettingsRead) -> InvoiceCreation:
        definition = settings.definition
        row, created = Invoice.objects.get_or_create(
            owner_id=values.actor_id,
            request_key=values.request_key,
            defaults={
                "customer_id": values.customer_id,
                "base_amount_minor": values.base_amount_minor,
                "settings_revision": settings.revision,
                "recipient": definition.recipient,
                "destination": definition.destination,
                "instructions": definition.instructions,
                "enabled": definition.enabled,
                "receipt_max_bytes": definition.receipt_max_bytes,
            },
        )
        return InvoiceCreation(invoice_read(row), created)

    def transition(self, values: InvoiceTransition) -> None:
        updated = (
            Invoice.objects.filter(
                pk=values.invoice_id,
                owner_id=values.actor_id,
                revision=values.expected_revision,
                revision__lt=MAX_MONEY_MINOR,
            )
            .exclude(status=InvoiceState.SETTLED)
            .update(status=values.status, revision=F("revision") + 1)
        )
        if updated != 1:
            raise Conflict("The invoice changed or was already settled. Read its current state.")

    def reserve_receipt(self, values: ReceiptSubmit) -> ReceiptReservation:
        attachment = values.file
        row, created = Receipt.objects.get_or_create(
            invoice_id=values.invoice_id,
            request_key=values.request_key,
            defaults={
                "reference": values.reference,
                "note": values.note,
                "filename": attachment.filename if attachment else "",
                "media_type": attachment.media_type if attachment else "",
                "size_bytes": len(attachment.data) if attachment else 0,
                "content": attachment.data if attachment else None,
            },
        )
        original = ReceiptSubmit(
            values.actor_id,
            row.invoice_id,
            row.request_key,
            row.reference,
            row.note,
            receipt_content(row),
        )
        return ReceiptReservation(receipt_read(row), original, created)

    def reserve_decision(self, values: DecisionInput) -> DecisionReservation:
        row, created = PaymentDecision.objects.get_or_create(
            actor_id=values.actor_id,
            request_key=values.request_key,
            defaults={
                "invoice_id": values.invoice_id,
                "expected_revision": values.expected_revision,
                "action": values.action,
                "reason": values.reason,
                "receipt_id": values.receipt_id,
            },
        )
        original = DecisionInput(
            row.actor_id,
            row.invoice_id,
            row.request_key,
            row.expected_revision,
            DecisionAction(row.action),
            row.reason,
            row.receipt_id,
        )
        return DecisionReservation(decision_read(row), original, created)

    def complete_decision(self, decision_id: UUID, actor_id: int, entry_id: UUID) -> None:
        updated = PaymentDecision.objects.filter(
            pk=decision_id, actor_id=actor_id, wallet_entry_id__isnull=True
        ).update(wallet_entry_id=entry_id)
        if updated != 1:
            raise Conflict("The payment decision already has a financial effect.")
