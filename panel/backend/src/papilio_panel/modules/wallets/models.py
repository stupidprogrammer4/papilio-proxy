"""Native BIGINT wallet balances and transaction-finalized journal entries."""

import uuid

from django.conf import settings
from django.db import models

from papilio_panel.shared.money import Currency

from .domain import EntryKind


class Wallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_id: uuid.UUID
    customer = models.OneToOneField("customers.CustomerAccount", on_delete=models.PROTECT)
    currency = models.CharField(
        max_length=3, choices=[(item.value, item.name) for item in Currency]
    )
    balance_minor = models.BigIntegerField(default=0)
    credit_limit_minor = models.BigIntegerField(default=0)
    revision = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)


class JournalEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet_id: uuid.UUID
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT)
    actor_id: int
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    kind = models.CharField(max_length=6, choices=[(item.value, item.name) for item in EntryKind])
    amount_minor = models.BigIntegerField()
    reason = models.CharField(max_length=500)
    balance_before_minor = models.BigIntegerField(null=True, editable=False)
    balance_after_minor = models.BigIntegerField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["wallet", "request_key"], name="wallets_entry_request"),
        ]
