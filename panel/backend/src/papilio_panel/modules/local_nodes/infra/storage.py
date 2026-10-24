"""Native scoped local runtime metadata and durable operation persistence."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from papilio_panel.modules.nodes.domain import AgentRuntime, CertificatePolicy, NodeDefinition
from papilio_panel.shared.errors import Conflict, Missing
from papilio_panel.shared.operations import OperationStatus

from ..domain import (
    DeliveryPolicy,
    DeliveryRead,
    DeliveryUpdate,
    LocalBinding,
    LocalCreation,
    LocalDefinition,
    LocalOperationRead,
    LocalRead,
    LocalRetry,
)
from ..models import LocalNodeInstallation, LocalNodeOperation


def definition_read(value: dict[str, Any]) -> LocalDefinition:
    node = value["node"]
    return LocalDefinition(
        NodeDefinition(
            node["name"],
            node["endpoint_url"],
            AgentRuntime(**node["runtime"]),
            CertificatePolicy(**node["certificate_policy"]),
        ),
        value["core_name"],
        value["inbound_tag"],
        value["public_host"],
        value["public_port"],
        value["default_user_level"],
        value["bind_address"],
        value["bind_port"],
    )


def operation_read(row: LocalNodeOperation) -> LocalOperationRead:
    return LocalOperationRead(
        row.id,
        row.request_key,
        OperationStatus(row.status),
        row.attempts,
        row.error_code,
        row.worker_pid,
        row.due_at,
        row.lease_until,
        row.completed_at,
        row.timeout_seconds,
    )


def installation_read(row: LocalNodeInstallation) -> LocalRead:
    operation = row.current_operation
    if operation is None:
        raise Missing("The local node delivery is not initialized.")
    return LocalRead(
        row.owner_id,
        row.request_key,
        row.node_id,
        row.issue_operation_id,
        row.core_id,
        row.inbound_id,
        definition_read(row.initial_definition),
        DeliveryPolicy(**row.initial_delivery),
        DeliveryRead(
            row.delivery_enabled, row.retry_interval_seconds, row.max_attempts, row.revision
        ),
        operation_read(operation),
    )


class DjangoLocalStorage:
    def current(self, actor_id: int) -> LocalRead | None:
        row = (
            LocalNodeInstallation.objects.select_related("current_operation")
            .filter(pk=1, owner_id=actor_id)
            .first()
        )
        return installation_read(row) if row is not None else None

    def create(self, values: LocalBinding) -> LocalCreation:
        supplied = values.values
        _, created = LocalNodeInstallation.objects.get_or_create(
            pk=1,
            defaults={
                "owner_id": supplied.actor_id,
                "request_key": supplied.request_key,
                "node_id": values.node_id,
                "issue_operation_id": values.issue_operation_id,
                "core_id": values.core_id,
                "inbound_id": values.inbound_id,
                "initial_definition": asdict(supplied.definition),
                "initial_delivery": asdict(supplied.delivery),
                "delivery_enabled": supplied.delivery.enabled,
                "retry_interval_seconds": supplied.delivery.retry_interval_seconds,
                "max_attempts": supplied.delivery.max_attempts,
            },
        )
        if created:
            operation = LocalNodeOperation.objects.create(
                installation_id=1,
                request_key=supplied.request_key,
                timeout_seconds=values.timeout_seconds,
            )
            LocalNodeInstallation.objects.filter(pk=1, owner_id=supplied.actor_id).update(
                current_operation=operation
            )
        record = self.current(supplied.actor_id)
        if record is None:
            raise Missing("The local node was not found.")
        return LocalCreation(record, created)

    def update_delivery(self, values: DeliveryUpdate) -> DeliveryRead:
        changed = LocalNodeInstallation.objects.filter(
            pk=1, owner_id=values.actor_id, revision=values.expected_revision
        ).update(
            delivery_enabled=values.policy.enabled,
            retry_interval_seconds=values.policy.retry_interval_seconds,
            max_attempts=values.policy.max_attempts,
            revision=F("revision") + 1,
        )
        if changed != 1:
            raise Conflict("The delivery settings changed. Reload before saving.")
        current = self.current(values.actor_id)
        if current is None:
            raise Missing("The local node was not found.")
        LocalNodeOperation.objects.filter(
            Q(status=OperationStatus.QUEUED)
            | Q(status=OperationStatus.RUNNING, lease_until__lte=timezone.now()),
            pk=current.operation.id,
            installation__owner_id=values.actor_id,
        ).update(due_at=timezone.now(), dispatched_at=None)
        return current.delivery

    @transaction.atomic
    def retry(self, values: LocalRetry) -> LocalOperationRead:
        try:
            installation = LocalNodeInstallation.objects.select_for_update().get(
                pk=1, owner_id=values.actor_id
            )
        except LocalNodeInstallation.DoesNotExist as error:
            raise Missing("The local node was not found.") from error
        current = installation_read(installation)
        operation, created = LocalNodeOperation.objects.get_or_create(
            installation_id=1,
            request_key=values.request_key,
            defaults={"timeout_seconds": current.operation.timeout_seconds},
        )
        if created:
            LocalNodeOperation.objects.filter(
                pk=current.operation.id,
                status__in=(OperationStatus.QUEUED, OperationStatus.RUNNING),
            ).update(
                status=OperationStatus.CANCELLED,
                completed_at=timezone.now(),
                lease_token=None,
                lease_until=None,
            )
            LocalNodeInstallation.objects.filter(pk=1, owner_id=values.actor_id).update(
                current_operation=operation
            )
        return operation_read(operation)

    def read_operation(self, operation_id: UUID, actor_id: int) -> LocalOperationRead:
        try:
            row = LocalNodeOperation.objects.get(
                pk=operation_id, installation_id=1, installation__owner_id=actor_id
            )
        except LocalNodeOperation.DoesNotExist as error:
            raise Missing("The local node operation was not found.") from error
        return operation_read(row)
