"""Durable local delivery with native transactions and current-operation fencing."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from papilio_panel.shared.errors import Missing
from papilio_panel.shared.operations import OperationStatus

from ..domain import LocalClaim, LocalDelivery, LocalWork
from ..models import LocalNodeInstallation, LocalNodeOperation
from .storage import installation_read, operation_read


class DjangoLocalWorkStorage:
    def read(self, operation_id: UUID) -> LocalWork:
        try:
            row = LocalNodeOperation.objects.select_related("installation__current_operation").get(
                pk=operation_id, installation_id=1
            )
        except LocalNodeOperation.DoesNotExist as error:
            raise Missing("The local node operation was not found.") from error
        return LocalWork(installation_read(row.installation), operation_read(row))

    @transaction.atomic
    def claim(self, operation_id: UUID) -> LocalClaim | None:
        installation = LocalNodeInstallation.objects.select_for_update().filter(pk=1).first()
        if (
            installation is None
            or not installation.delivery_enabled
            or installation.current_operation_id != operation_id
        ):
            return None
        now, token = timezone.now(), uuid4()
        eligible = Q(status=OperationStatus.QUEUED) | Q(
            status=OperationStatus.RUNNING, lease_until__lte=now
        )
        operation = LocalNodeOperation.objects.get(pk=operation_id, installation_id=1)
        scoped = LocalNodeOperation.objects.filter(eligible, pk=operation_id, due_at__lte=now)
        if operation.attempts >= installation.max_attempts:
            scoped.update(
                status=OperationStatus.FAILED,
                error_code="retry_exhausted",
                completed_at=now,
                lease_token=None,
                lease_until=None,
            )
            return None
        changed = scoped.update(
            status=OperationStatus.RUNNING,
            attempts=F("attempts") + 1,
            lease_token=token,
            lease_until=now + timedelta(seconds=operation.timeout_seconds + 30),
            worker_pid=os.getpid(),
            dispatched_at=None,
        )
        return LocalClaim(self.read(operation_id), token) if changed else None

    def active(self, claim: LocalClaim) -> bool:
        return LocalNodeOperation.objects.filter(
            pk=claim.work.operation.id,
            installation_id=1,
            installation__owner_id=claim.work.record.owner_id,
            installation__current_operation_id=claim.work.operation.id,
            installation__delivery_enabled=True,
            status=OperationStatus.RUNNING,
            lease_token=claim.token,
            lease_until__gt=timezone.now(),
        ).exists()

    def release(self, claim: LocalClaim) -> None:
        LocalNodeOperation.objects.filter(
            pk=claim.work.operation.id,
            installation_id=1,
            installation__owner_id=claim.work.record.owner_id,
            installation__current_operation_id=claim.work.operation.id,
            status=OperationStatus.RUNNING,
            lease_token=claim.token,
        ).update(
            status=OperationStatus.QUEUED,
            lease_token=None,
            lease_until=None,
            dispatched_at=None,
            due_at=timezone.now(),
        )

    @transaction.atomic
    def finish(self, claim: LocalClaim, error_code: str | None, *, retryable: bool) -> None:
        installation = (
            LocalNodeInstallation.objects.select_for_update()
            .filter(
                pk=1,
                owner_id=claim.work.record.owner_id,
                current_operation_id=claim.work.operation.id,
            )
            .first()
        )
        if installation is None:
            return
        now = timezone.now()
        retry = not installation.delivery_enabled or (
            error_code is not None
            and retryable
            and claim.work.operation.attempts < installation.max_attempts
        )
        status = OperationStatus.SUCCEEDED if error_code is None else OperationStatus.FAILED
        LocalNodeOperation.objects.filter(
            pk=claim.work.operation.id,
            installation_id=1,
            status=OperationStatus.RUNNING,
            lease_token=claim.token,
            lease_until__gt=now,
        ).update(
            status=OperationStatus.QUEUED if retry else status,
            error_code=error_code,
            worker_pid=os.getpid(),
            due_at=now + timedelta(seconds=installation.retry_interval_seconds),
            completed_at=None if retry else now,
            lease_token=None,
            lease_until=None,
            dispatched_at=None,
        )

    def pending(self) -> LocalDelivery | None:
        now = timezone.now()
        stale = now - timedelta(seconds=settings.PAPILIO_OUTBOX_REDELIVERY_SECONDS)
        eligible = Q(status=OperationStatus.QUEUED) | Q(
            status=OperationStatus.RUNNING, lease_until__lte=now
        )
        undispatched = Q(dispatched_at__isnull=True) | Q(dispatched_at__lte=stale)
        row = LocalNodeOperation.objects.filter(
            eligible,
            undispatched,
            installation_id=1,
            installation__delivery_enabled=True,
            installation__current_operation_id=F("pk"),
            due_at__lte=now,
        ).first()
        return (
            LocalDelivery(row.id, row.timeout_seconds, row.attempts, row.due_at)
            if row is not None
            else None
        )

    def dispatched(self, delivery: LocalDelivery) -> None:
        LocalNodeOperation.objects.filter(
            pk=delivery.operation_id,
            installation_id=1,
            installation__current_operation_id=delivery.operation_id,
            installation__delivery_enabled=True,
            status__in=(OperationStatus.QUEUED, OperationStatus.RUNNING),
            attempts=delivery.attempts,
            due_at=delivery.due_at,
        ).update(dispatched_at=timezone.now())
