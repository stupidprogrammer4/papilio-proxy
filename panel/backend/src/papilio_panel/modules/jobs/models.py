"""Native persistence for an operation aggregate and worker health facts."""

import uuid

from django.conf import settings
from django.db import models

from .domain import OperationStatus, ProbeKind


class Operation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    kind = models.CharField(max_length=16, choices=[(item.value, item.value) for item in ProbeKind])
    status = models.CharField(
        max_length=16,
        choices=[(item.value, item.value) for item in OperationStatus],
        default=OperationStatus.QUEUED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    result = models.JSONField(null=True)
    error_code = models.CharField(max_length=64, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["actor", "request_key"], name="jobs_actor_request_key"),
        ]
        indexes = [models.Index(fields=["status", "lease_until"])]


class OutboxMessage(models.Model):
    operation = models.OneToOneField(Operation, primary_key=True, on_delete=models.CASCADE)
    dispatched_at = models.DateTimeField(null=True, db_index=True)


class WorkerHeartbeat(models.Model):
    role = models.CharField(primary_key=True, max_length=16)
    queue = models.CharField(max_length=160)
    worker_host = models.CharField(max_length=255)
    worker_pid = models.PositiveIntegerField()
    observed_at = models.DateTimeField()
