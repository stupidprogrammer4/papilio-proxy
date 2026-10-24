"""One physical bundled runtime and its durable preparation operations."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from papilio_panel.shared.operations import OperationStatus


class LocalNodeInstallation(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    node_id: uuid.UUID
    node = models.OneToOneField("nodes.Node", on_delete=models.PROTECT)
    issue_operation_id: uuid.UUID
    issue_operation = models.ForeignKey("nodes.NodeOperation", on_delete=models.PROTECT)
    core_id: uuid.UUID
    core = models.OneToOneField("cores.Core", on_delete=models.PROTECT)
    inbound_id: uuid.UUID
    inbound = models.OneToOneField("cores.XrayInbound", on_delete=models.PROTECT)
    initial_definition = models.JSONField()
    initial_delivery = models.JSONField()
    delivery_enabled = models.BooleanField(default=True)
    retry_interval_seconds = models.IntegerField(default=1)
    max_attempts = models.IntegerField(default=5)
    revision = models.BigIntegerField(default=1)
    current_operation_id: uuid.UUID | None
    current_operation = models.ForeignKey(
        "LocalNodeOperation", null=True, on_delete=models.PROTECT, related_name="+"
    )


class LocalNodeOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installation = models.ForeignKey(LocalNodeInstallation, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    status = models.CharField(max_length=16, default=OperationStatus.QUEUED)
    timeout_seconds = models.BigIntegerField()
    attempts = models.BigIntegerField(default=0)
    due_at = models.DateTimeField(default=timezone.now)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, null=True)
    worker_pid = models.BigIntegerField(null=True)
    dispatched_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["installation", "request_key"], name="local_nodes_operation_request"
            )
        ]
        indexes = [models.Index(fields=["status", "due_at"])]
