"""Common service state with separate Xray credentials and inbound binding."""

import uuid

from django.conf import settings
from django.db import models

from papilio_panel.shared.operations import OperationStatus


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

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "request_key"], name="services_owner_request")
        ]
        indexes = [models.Index(fields=["status", "lease_until"])]


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
