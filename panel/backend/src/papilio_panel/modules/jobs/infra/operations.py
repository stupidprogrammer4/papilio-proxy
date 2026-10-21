"""Set-based native Django operation storage and conditional claims."""

from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from papilio_panel.shared.errors import Missing

from ..domain import (
    Delivery,
    ExecutionClaim,
    OperationCreation,
    OperationRead,
    OperationStatus,
    ProbeKind,
    ProbeResult,
    ProbeSubmission,
)
from ..models import Operation, OutboxMessage


def operation_read(row: Operation) -> OperationRead:
    result = ProbeResult(**row.result) if row.result is not None else None
    return OperationRead(
        id=row.id,
        kind=ProbeKind(row.kind),
        status=OperationStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        attempts=row.attempts,
        result=result,
        error_code=row.error_code,
        lease_until=row.lease_until,
    )


class DjangoOperationStorage:
    def create(self, values: ProbeSubmission) -> OperationCreation:
        row, created = Operation.objects.get_or_create(
            actor_id=values.actor_id,
            request_key=values.request_key,
            defaults={"kind": values.kind.value},
        )
        return OperationCreation(operation=operation_read(row), created=created)

    def add_outbox(self, operation_id: UUID) -> None:
        OutboxMessage.objects.create(operation_id=operation_id)

    def read(self, operation_id: UUID, actor_id: int) -> OperationRead:
        try:
            row = Operation.objects.get(pk=operation_id, actor_id=actor_id)
        except Operation.DoesNotExist as error:
            raise Missing("The operation was not found.") from error
        return operation_read(row)

    def cancel_queued(self, operation_id: UUID, actor_id: int) -> None:
        Operation.objects.filter(
            pk=operation_id, actor_id=actor_id, status=OperationStatus.QUEUED
        ).update(status=OperationStatus.CANCELLED, updated_at=timezone.now())

    def claim(self, operation_id: UUID, kind: ProbeKind) -> ExecutionClaim:
        now = timezone.now()
        token = uuid4()
        eligible = Q(status=OperationStatus.QUEUED) | Q(
            status=OperationStatus.RUNNING, lease_until__lt=now
        )
        Operation.objects.filter(
            eligible,
            pk=operation_id,
            kind=kind.value,
            attempts__gte=settings.PAPILIO_OPERATION_MAX_ATTEMPTS,
        ).update(status=OperationStatus.FAILED, error_code="retry_exhausted", updated_at=now)
        changed = Operation.objects.filter(
            eligible,
            pk=operation_id,
            kind=kind.value,
            attempts__lt=settings.PAPILIO_OPERATION_MAX_ATTEMPTS,
        ).update(
            status=OperationStatus.RUNNING,
            lease_token=token,
            lease_until=now + timedelta(seconds=settings.PAPILIO_OPERATION_LEASE_SECONDS),
            attempts=F("attempts") + 1,
            updated_at=now,
        )
        try:
            row = Operation.objects.get(pk=operation_id)
        except Operation.DoesNotExist as error:
            raise Missing("The operation was not found.") from error
        return ExecutionClaim(
            operation=operation_read(row), token=token if changed else None, actor_id=row.actor.pk
        )

    def reject(self, operation_id: UUID, token: UUID, error_code: str) -> None:
        Operation.objects.filter(
            pk=operation_id, lease_token=token, status=OperationStatus.RUNNING
        ).update(
            status=OperationStatus.FAILED,
            error_code=error_code,
            lease_token=None,
            lease_until=None,
            updated_at=timezone.now(),
        )

    def finish(self, operation_id: UUID, token: UUID, result: ProbeResult) -> None:
        Operation.objects.filter(
            pk=operation_id, lease_token=token, status=OperationStatus.RUNNING
        ).update(
            status=OperationStatus.SUCCEEDED,
            result=asdict(result),
            lease_until=None,
            lease_token=None,
            error_code=None,
            updated_at=timezone.now(),
        )

    def pending_deliveries(self) -> tuple[Delivery, ...]:
        now = timezone.now()
        retry_before = now - timedelta(seconds=settings.PAPILIO_OUTBOX_REDELIVERY_SECONDS)
        pending = Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=retry_before)
        eligible = Q(operation__status=OperationStatus.QUEUED) | Q(
            operation__status=OperationStatus.RUNNING, operation__lease_until__lt=now
        )
        rows = (
            OutboxMessage.objects.filter(pending, eligible)
            .select_related("operation")
            .order_by("operation__created_at")[: settings.PAPILIO_OUTBOX_BATCH_SIZE]
        )
        return tuple(
            Delivery(operation_id=row.operation.id, kind=ProbeKind(row.operation.kind))
            for row in rows
        )

    def mark_dispatched(self, deliveries: tuple[Delivery, ...]) -> None:
        OutboxMessage.objects.filter(
            operation_id__in=[delivery.operation_id for delivery in deliveries]
        ).update(dispatched_at=timezone.now())
