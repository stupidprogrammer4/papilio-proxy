"""Native owner configuration and invoice aggregate persistence."""

import uuid

from django.conf import settings
from django.db import models

from .domain import (
    DEFAULT_INVOICE_ISSUANCE_ENABLED,
    DEFAULT_RECEIPT_MAX_BYTES,
    DecisionAction,
    InvoiceState,
)


class PaymentSettings(models.Model):
    owner_id: int
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.BigIntegerField(default=1)
    recipient = models.CharField(max_length=80)
    destination = models.CharField(max_length=120)
    instructions = models.CharField(max_length=2000, blank=True)
    enabled = models.BooleanField(default=DEFAULT_INVOICE_ISSUANCE_ENABLED)
    receipt_max_bytes = models.PositiveIntegerField(default=DEFAULT_RECEIPT_MAX_BYTES)


class Invoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    customer_id: uuid.UUID
    customer = models.ForeignKey("customers.CustomerAccount", on_delete=models.PROTECT)
    request_key = models.UUIDField()
    base_amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3, default="IRR")
    status = models.CharField(
        max_length=12, default=InvoiceState.OPEN, choices=[(s.value, s.name) for s in InvoiceState]
    )
    revision = models.BigIntegerField(default=1)
    settings_revision = models.BigIntegerField()
    recipient = models.CharField(max_length=80)
    destination = models.CharField(max_length=120)
    instructions = models.CharField(max_length=2000, blank=True)
    enabled = models.BooleanField()
    receipt_max_bytes = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "request_key"], name="payments_invoice_request"
            )
        ]


class Receipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_id: uuid.UUID
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    reference = models.CharField(max_length=200, blank=True)
    note = models.CharField(max_length=2000, blank=True)
    filename = models.CharField(max_length=255, blank=True)
    media_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    content = models.BinaryField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "request_key"], name="payments_receipt_request"
            )
        ]


class PaymentDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_id: uuid.UUID
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT)
    actor_id: int
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    expected_revision = models.BigIntegerField()
    action = models.CharField(max_length=8, choices=[(s.value, s.name) for s in DecisionAction])
    reason = models.CharField(max_length=500)
    receipt_id: uuid.UUID | None
    receipt = models.ForeignKey(Receipt, null=True, on_delete=models.PROTECT)
    wallet_entry_id: uuid.UUID | None
    wallet_entry = models.OneToOneField("wallets.JournalEntry", null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["actor", "request_key"], name="payments_decision_request"
            )
        ]
