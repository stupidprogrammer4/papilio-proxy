"""Native conditional writes for the node aggregate and its durable work."""

import json
import os
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from papilio_panel.shared.credentials import credential_cipher
from papilio_panel.shared.errors import Missing
from papilio_panel.shared.operations import OperationStatus

from ..domain import (
    IssuedCredentials,
    NodeCreate,
    NodeCreation,
    NodeWorkKind,
    ProbeObservation,
    WorkClaim,
    WorkCreation,
    WorkDelivery,
    WorkSubmission,
)
from ..models import (
    AgentSettings,
    CredentialPolicy,
    DeploymentIdentity,
    Node,
    NodeCredentials,
    NodeOperation,
    NodeOutbox,
)
from .readers import DjangoNodeReader, definition_read, node_read, work_read


class DjangoNodeStorage(DjangoNodeReader):
    def create(self, values: NodeCreate) -> NodeCreation:
        deployment, _ = DeploymentIdentity.objects.get_or_create(pk=1)
        node, created = Node.objects.get_or_create(
            owner_id=values.actor_id,
            request_key=values.request_key,
            defaults={
                "deployment": deployment,
                "name": values.definition.name,
                "endpoint_url": values.definition.endpoint_url,
                "initial_definition": asdict(values.definition),
            },
        )
        if created:
            AgentSettings.objects.create(node=node, **asdict(values.definition.runtime))
            CredentialPolicy.objects.create(
                node=node, **asdict(values.definition.certificate_policy)
            )
            work = self.create_work(
                WorkSubmission(
                    actor_id=values.actor_id,
                    node_id=node.id,
                    request_key=values.request_key,
                    kind=NodeWorkKind.ISSUE,
                )
            ).operation
        else:
            work = work_read(
                NodeOperation.objects.get(actor_id=values.actor_id, request_key=values.request_key)
            )
        return NodeCreation(
            node=self.read(node.id, values.actor_id),
            operation=work,
            created=created,
            original_definition=definition_read(node.initial_definition),
        )

    def create_work(self, values: WorkSubmission) -> WorkCreation:
        try:
            node = Node.objects.select_related("runtime").get(
                pk=values.node_id, owner_id=values.actor_id
            )
        except Node.DoesNotExist as error:
            raise Missing("The node was not found.") from error
        operation, created = NodeOperation.objects.get_or_create(
            actor_id=values.actor_id,
            request_key=values.request_key,
            defaults={
                "node": node,
                "kind": values.kind.value,
                "timeout_seconds": 3 * node.runtime.request_timeout_seconds + 10,
            },
        )
        if created:
            Node.objects.filter(pk=node.id, owner_id=values.actor_id).update(
                last_operation=operation
            )
        return WorkCreation(operation=work_read(operation), created=created)

    def add_outbox(self, operation_id: UUID) -> None:
        NodeOutbox.objects.create(operation_id=operation_id)

    def claim(self, operation_id: UUID, kind: NodeWorkKind) -> WorkClaim:
        now, token = timezone.now(), uuid4()
        eligible = Q(status=OperationStatus.QUEUED) | Q(
            status=OperationStatus.RUNNING, lease_until__lt=now
        )
        maximum = settings.PAPILIO_OPERATION_MAX_ATTEMPTS
        NodeOperation.objects.filter(
            eligible, pk=operation_id, kind=kind.value, attempts__gte=maximum
        ).update(
            status=OperationStatus.FAILED,
            error_code="retry_exhausted",
            completed_at=now,
        )
        try:
            current = NodeOperation.objects.get(pk=operation_id)
        except NodeOperation.DoesNotExist as error:
            raise Missing("The node operation was not found.") from error
        changed = NodeOperation.objects.filter(
            eligible, pk=operation_id, kind=kind.value, attempts__lt=maximum
        ).update(
            status=OperationStatus.RUNNING,
            attempts=F("attempts") + 1,
            lease_token=token,
            lease_until=now + timedelta(seconds=current.timeout_seconds + 30),
        )
        row = (
            NodeOperation.objects.select_related(
                "node__deployment",
                "node__runtime",
                "node__certificate_policy",
                "node__credentials",
            )
            .defer("node__credentials__secrets_ciphertext")
            .get(pk=operation_id)
        )
        return WorkClaim(
            operation=work_read(row), node=node_read(row.node), token=token if changed else None
        )

    def reject(self, operation_id: UUID, token: UUID, error_code: str) -> None:
        NodeOperation.objects.filter(
            pk=operation_id, status=OperationStatus.RUNNING, lease_token=token
        ).update(
            status=OperationStatus.FAILED,
            error_code=error_code,
            completed_at=timezone.now(),
            lease_token=None,
            lease_until=None,
            worker_pid=os.getpid(),
        )

    @transaction.atomic
    def finish_issue(self, claim: WorkClaim, credentials: IssuedCredentials) -> None:
        changed = NodeOperation.objects.filter(
            pk=claim.operation.id,
            lease_token=claim.token,
            status=OperationStatus.RUNNING,
            node__owner_id=claim.operation.actor_id,
        ).update(
            status=OperationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            lease_token=None,
            lease_until=None,
            worker_pid=os.getpid(),
            error_code=None,
        )
        if changed:
            ciphertext = credential_cipher().encrypt(
                json.dumps(asdict(credentials.private_keys)).encode()
            )
            NodeCredentials.objects.get_or_create(
                node_id=claim.node.id,
                defaults={
                    "authority_certificate": credentials.authority_certificate,
                    "server_certificate": credentials.server_certificate,
                    "control_certificate": credentials.control_certificate,
                    "secrets_ciphertext": ciphertext,
                    "expires_at": credentials.expires_at,
                },
            )

    @transaction.atomic
    def finish_check(self, claim: WorkClaim, result: ProbeObservation) -> None:
        now = timezone.now()
        changed = NodeOperation.objects.filter(
            pk=claim.operation.id,
            lease_token=claim.token,
            status=OperationStatus.RUNNING,
            node__owner_id=claim.operation.actor_id,
        ).update(
            status=OperationStatus.SUCCEEDED if result.reachable else OperationStatus.FAILED,
            error_code=result.error_code,
            completed_at=now,
            lease_token=None,
            lease_until=None,
            worker_pid=os.getpid(),
        )
        if changed:
            Node.objects.filter(pk=claim.node.id, owner_id=claim.operation.actor_id).update(
                last_reachable=result.reachable,
                last_checked_at=now,
                last_error_code=result.error_code,
                uptime_seconds=result.uptime_seconds,
            )

    def pending_deliveries(self) -> tuple[WorkDelivery, ...]:
        now = timezone.now()
        before = now - timedelta(seconds=settings.PAPILIO_OUTBOX_REDELIVERY_SECONDS)
        pending = Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=before)
        active = Q(operation__status=OperationStatus.QUEUED) | Q(
            operation__status=OperationStatus.RUNNING, operation__lease_until__lt=now
        )
        rows = (
            NodeOutbox.objects.filter(pending, active)
            .select_related("operation")
            .order_by(
                "operation__created_at",
                "operation_id",
            )[: settings.PAPILIO_OUTBOX_BATCH_SIZE]
        )
        return tuple(
            WorkDelivery(
                operation_id=row.operation_id,
                kind=NodeWorkKind(row.operation.kind),
                timeout_seconds=row.operation.timeout_seconds,
            )
            for row in rows
        )

    def mark_dispatched(self, deliveries: tuple[WorkDelivery, ...]) -> None:
        NodeOutbox.objects.filter(
            operation_id__in=[item.operation_id for item in deliveries]
        ).update(dispatched_at=timezone.now())
