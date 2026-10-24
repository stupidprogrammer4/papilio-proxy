"""Native per-bot shop policy, customer bindings and independent durable work."""

import uuid

from django.conf import settings
from django.db import models

from .domain import MessageState, ShopDefinition, WorkState, default_texts


class ShopConfiguration(models.Model):
    bot_id: uuid.UUID
    bot = models.OneToOneField(
        "bots.Bot", on_delete=models.PROTECT, related_name="shop_configuration"
    )
    revision = models.BigIntegerField(default=1)
    public_origin = models.URLField(max_length=500)
    enabled = models.BooleanField(default=ShopDefinition.enabled)
    delivery_enabled = models.BooleanField(default=ShopDefinition.delivery_enabled)
    locale = models.CharField(max_length=2, default=ShopDefinition.locale)
    page_size = models.PositiveIntegerField(default=ShopDefinition.page_size)
    retry_seconds = models.PositiveIntegerField(default=ShopDefinition.retry_seconds)
    lease_seconds = models.PositiveIntegerField(default=ShopDefinition.lease_seconds)
    max_attempts = models.PositiveIntegerField(default=ShopDefinition.max_attempts)
    confirmation_ttl_seconds = models.PositiveIntegerField(
        default=ShopDefinition.confirmation_ttl_seconds
    )
    ambiguous_delivery = models.CharField(max_length=5, default=ShopDefinition.ambiguous_delivery)
    texts = models.JSONField(default=default_texts)


class ShopCustomer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    telegram_user_id = models.BigIntegerField()
    customer_id: uuid.UUID | None
    customer = models.OneToOneField(
        "customers.CustomerAccount", null=True, on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "telegram_user_id"], name="shop_owner_telegram_user"
            )
        ]


class InboxWork(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id: int
    event = models.OneToOneField(
        "bots.TelegramInbox", on_delete=models.PROTECT, related_name="shop_work"
    )
    status = models.CharField(max_length=8, default=WorkState.QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    retry_at = models.DateTimeField(null=True)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    dispatched_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, null=True)
    worker_pid = models.PositiveIntegerField(null=True)


class PurchaseIntent(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    bot_id: uuid.UUID
    bot = models.ForeignKey("bots.Bot", on_delete=models.PROTECT)
    customer_id: uuid.UUID
    customer = models.ForeignKey("customers.CustomerAccount", on_delete=models.PROTECT)
    product_id: uuid.UUID
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT)
    offer_revision = models.BigIntegerField()
    service_name = models.CharField(max_length=80)
    expires_at = models.DateTimeField()
    order_id: uuid.UUID | None
    order = models.OneToOneField("orders.Order", null=True, on_delete=models.PROTECT)


class OutgoingMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id: int
    event = models.ForeignKey("bots.TelegramInbox", on_delete=models.PROTECT)
    bot_id: uuid.UUID
    bot = models.ForeignKey("bots.Bot", on_delete=models.PROTECT)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    administrator = models.BooleanField(default=False)
    invoice_id: uuid.UUID | None
    invoice = models.ForeignKey("payments.Invoice", null=True, on_delete=models.PROTECT)
    source_event_id: uuid.UUID | None
    source_event = models.OneToOneField(
        "payments.PaymentDecisionEvent", null=True, on_delete=models.PROTECT
    )
    payload_ciphertext = models.BinaryField(editable=False)
    status = models.CharField(max_length=12, default=MessageState.QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    retry_at = models.DateTimeField(null=True)
    dispatched_at = models.DateTimeField(null=True)
    message_id = models.BigIntegerField(null=True)
    chat_id = models.BigIntegerField(null=True)
    error_code = models.CharField(max_length=64, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class InvoiceConversation(models.Model):
    invoice_id: uuid.UUID
    invoice = models.OneToOneField("payments.Invoice", primary_key=True, on_delete=models.PROTECT)
    event_id: int
    event = models.ForeignKey("bots.TelegramInbox", on_delete=models.PROTECT)
