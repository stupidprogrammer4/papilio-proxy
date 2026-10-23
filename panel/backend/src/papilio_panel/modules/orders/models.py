"""Native accepted purchase terms and one-to-one financial/service effects."""

import uuid

from django.conf import settings
from django.db import models

from .domain import OrderState


class Order(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    customer_id: uuid.UUID
    customer = models.ForeignKey("customers.CustomerAccount", on_delete=models.PROTECT)
    product_id: uuid.UUID
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT)
    offer_id: uuid.UUID
    offer = models.ForeignKey("catalog.ProductOffer", on_delete=models.PROTECT)
    offer_revision = models.BigIntegerField()
    product_name = models.CharField(max_length=80)
    price_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    core_id: uuid.UUID
    core = models.ForeignKey("cores.Core", on_delete=models.PROTECT)
    inbound_id: uuid.UUID
    inbound = models.ForeignKey("cores.XrayInbound", on_delete=models.PROTECT)
    user_level = models.BigIntegerField()
    service_name = models.CharField(max_length=80)
    status = models.CharField(
        max_length=12,
        choices=[(item.value, item.name) for item in OrderState],
        default=OrderState.PENDING,
    )
    service_id: uuid.UUID | None
    service = models.OneToOneField("services.ServiceAccount", on_delete=models.PROTECT, null=True)
    wallet_entry_id: uuid.UUID | None
    wallet_entry = models.OneToOneField("wallets.JournalEntry", on_delete=models.PROTECT, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "request_key"], name="orders_owner_request")
        ]
