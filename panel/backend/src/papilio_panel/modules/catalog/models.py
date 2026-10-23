"""Native product identity and append-only offer revision persistence."""

import uuid

from django.conf import settings
from django.db import models

from papilio_panel.shared.money import Currency


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    revision = models.BigIntegerField(default=1)
    current_offer = models.OneToOneField(
        "ProductOffer", null=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "request_key"], name="catalog_owner_request")
        ]


class ProductOffer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_id: uuid.UUID
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="offers")
    revision = models.BigIntegerField()
    name = models.CharField(max_length=80)
    core_id: uuid.UUID
    core = models.ForeignKey("cores.Core", on_delete=models.PROTECT)
    inbound_id: uuid.UUID
    inbound = models.ForeignKey("cores.XrayInbound", on_delete=models.PROTECT)
    currency = models.CharField(max_length=3, default=Currency.IRR)
    price_minor = models.BigIntegerField()
    requested_user_level = models.BigIntegerField(null=True)
    user_level = models.BigIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "revision"], name="catalog_offer_revision")
        ]
