"""Native persistence for node configuration and its onboarding operation aggregate."""

import uuid

from django.conf import settings
from django.db import models

from papilio_panel.shared.operations import OperationStatus

from .domain import NodeWorkKind


class DeploymentIdentity(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    deployment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)


class Node(models.Model):
    runtime: "AgentSettings"
    certificate_policy: "CredentialPolicy"
    credentials: "NodeCredentials"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    deployment = models.ForeignKey(DeploymentIdentity, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    name = models.CharField(max_length=80)
    endpoint_url = models.URLField(max_length=500)
    initial_definition = models.JSONField()
    last_reachable = models.BooleanField(null=True)
    last_checked_at = models.DateTimeField(null=True)
    last_error_code = models.CharField(max_length=64, null=True)
    uptime_seconds = models.BigIntegerField(null=True)
    last_operation_id: uuid.UUID | None
    last_operation = models.ForeignKey(
        "NodeOperation",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "request_key"],
                name="nodes_owner_request_key",
            )
        ]


class AgentSettings(models.Model):
    node = models.OneToOneField(
        Node, primary_key=True, on_delete=models.CASCADE, related_name="runtime"
    )
    listen_address = models.CharField(max_length=255, default="0.0.0.0:9443")
    xray_api_address = models.CharField(max_length=255, default="127.0.0.1:10085")
    request_timeout_seconds = models.IntegerField(default=15)
    read_header_timeout_seconds = models.IntegerField(default=5)
    idle_timeout_seconds = models.IntegerField(default=60)
    shutdown_timeout_seconds = models.IntegerField(default=20)
    max_body_bytes = models.BigIntegerField(default=1048576)
    max_grpc_reply_bytes = models.IntegerField(default=16777216)


class CredentialPolicy(models.Model):
    node = models.OneToOneField(
        Node, primary_key=True, on_delete=models.CASCADE, related_name="certificate_policy"
    )
    validity_seconds = models.IntegerField(default=2592000)
    authority_validity_seconds = models.IntegerField(default=31536000)
    backdate_seconds = models.IntegerField(default=60)


class NodeCredentials(models.Model):
    node = models.OneToOneField(
        Node, primary_key=True, on_delete=models.CASCADE, related_name="credentials"
    )
    authority_certificate = models.TextField()
    server_certificate = models.TextField()
    control_certificate = models.TextField()
    secrets_ciphertext = models.BinaryField(editable=False)
    expires_at = models.DateTimeField()


class NodeOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node_id: uuid.UUID
    node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="operations")
    actor_id: int
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    kind = models.CharField(
        max_length=24, choices=[(item.value, item.value) for item in NodeWorkKind]
    )
    status = models.CharField(
        max_length=16,
        choices=[(item.value, item.value) for item in OperationStatus],
        default=OperationStatus.QUEUED,
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
            models.UniqueConstraint(
                fields=["actor", "request_key"], name="nodes_work_actor_request"
            )
        ]
        indexes = [models.Index(fields=["status", "lease_until"])]


class NodeOutbox(models.Model):
    operation_id: uuid.UUID
    operation = models.OneToOneField(NodeOperation, primary_key=True, on_delete=models.CASCADE)
    dispatched_at = models.DateTimeField(null=True, db_index=True)
