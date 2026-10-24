"""Common service state with separate Xray credentials and inbound binding."""

import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from papilio_panel.shared.operations import OperationStatus

from .synchronization_contracts import INITIAL_SYNCHRONIZATION_SECONDS


def initial_synchronization_due() -> datetime:
    return timezone.now() + timedelta(seconds=INITIAL_SYNCHRONIZATION_SECONDS)


class ServiceAccount(models.Model):
    xray: "XrayService"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    core_id: uuid.UUID
    core = models.ForeignKey("cores.Core", on_delete=models.PROTECT)
    request_key = models.UUIDField()
    name = models.CharField(max_length=80)
    subscription_nonce = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=16,
        default=OperationStatus.QUEUED,
        choices=[(item.value, item.value) for item in OperationStatus],
    )
    timeout_seconds = models.BigIntegerField()
    attempts = models.IntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, null=True)
    worker_pid = models.BigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)
    sync_enabled = models.BooleanField(default=True)
    sync_interval_seconds = models.IntegerField(default=INITIAL_SYNCHRONIZATION_SECONDS)
    sync_revision = models.BigIntegerField(default=1)
    sync_generation = models.BigIntegerField(default=1)
    sync_status = models.CharField(max_length=16, default=OperationStatus.QUEUED)
    sync_attempts = models.BigIntegerField(default=0)
    sync_error_code = models.CharField(max_length=64, null=True)
    sync_worker_pid = models.BigIntegerField(null=True)
    sync_lease_token = models.UUIDField(null=True)
    sync_lease_until = models.DateTimeField(null=True)
    sync_due_at = models.DateTimeField(default=initial_synchronization_due)
    sync_last_completed_at = models.DateTimeField(null=True)
    sync_dispatched_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "request_key"], name="services_owner_request")
        ]
        indexes = [
            models.Index(fields=["status", "lease_until"]),
            models.Index(fields=["sync_enabled", "sync_due_at"]),
        ]


class XrayService(models.Model):
    service = models.OneToOneField(
        ServiceAccount, primary_key=True, on_delete=models.CASCADE, related_name="xray"
    )
    inbound_id: uuid.UUID
    inbound = models.ForeignKey("cores.XrayInbound", on_delete=models.PROTECT)
    credential_ciphertext = models.BinaryField(editable=False)
    credential_supplied = models.BooleanField()
    requested_level = models.BigIntegerField(null=True)
    level = models.BigIntegerField()
    email = models.CharField(max_length=64)


class ServiceOutbox(models.Model):
    service_id: uuid.UUID
    service = models.OneToOneField(ServiceAccount, primary_key=True, on_delete=models.CASCADE)
    dispatched_at = models.DateTimeField(null=True, db_index=True)
