"""Native persistence for each operator's configured bot and durable inbox."""

import uuid

from django.conf import settings
from django.db import models
from django_celery_beat.models import PeriodicTask

from .domain import BotRuntime


class Bot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    input_digest = models.CharField(max_length=64)
    label = models.CharField(max_length=80)
    revision = models.BigIntegerField(default=1)
    token_ciphertext = models.BinaryField(editable=False)
    token_digest = models.CharField(max_length=64, unique=True)
    periodic_task = models.OneToOneField(PeriodicTask, on_delete=models.PROTECT)
    api_base_url = models.URLField(max_length=500, default=BotRuntime.api_base_url)
    poll_timeout_seconds = models.IntegerField(default=BotRuntime.poll_timeout_seconds)
    http_timeout_seconds = models.IntegerField(default=BotRuntime.http_timeout_seconds)
    update_limit = models.IntegerField(default=BotRuntime.update_limit)
    max_response_bytes = models.IntegerField(default=BotRuntime.max_response_bytes)
    pairing_ttl_seconds = models.IntegerField(default=BotRuntime.pairing_ttl_seconds)
    failure_retry_seconds = models.IntegerField(default=BotRuntime.failure_retry_seconds)
    next_poll_after = models.DateTimeField(null=True)
    telegram_id = models.BigIntegerField(null=True)
    username = models.CharField(max_length=64, null=True)
    verified_revision = models.BigIntegerField(null=True)
    admin_chat_id = models.BigIntegerField(null=True)
    pairing_digest = models.CharField(max_length=64, null=True)
    pairing_expires_at = models.DateTimeField(null=True)
    next_update_id = models.BigIntegerField(default=0)
    last_poll_at = models.DateTimeField(null=True)
    last_error_code = models.CharField(max_length=64, null=True)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "request_key"], name="bots_owner_request_key"),
            models.UniqueConstraint(fields=["telegram_id"], name="bots_telegram_identity"),
        ]


class TelegramInbox(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    update_id = models.BigIntegerField()
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["bot", "update_id"], name="bots_inbox_update"),
        ]
