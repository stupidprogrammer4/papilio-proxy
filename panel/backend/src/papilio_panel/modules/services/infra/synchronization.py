"""Native scoped synchronization policy and generation-fenced work persistence."""

import os
from datetime import timedelta
from functools import reduce
from operator import or_
from uuid import UUID, uuid4

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from papilio_panel.shared.errors import Conflict, Missing
from papilio_panel.shared.operations import OperationStatus

from ..models import ServiceAccount
from ..synchronization_contracts import (
    SynchronizationClaim,
    SynchronizationDelivery,
    SynchronizationRead,
    SynchronizationUpdate,
)
from .readers import authorized_services, service_read


def synchronization_read(row: ServiceAccount) -> SynchronizationRead:
    return SynchronizationRead(
        row.id,
        row.sync_enabled,
        row.sync_interval_seconds,
        row.sync_revision,
        row.sync_generation,
        OperationStatus(row.sync_status),
        row.sync_attempts,
        row.sync_error_code,
        row.sync_worker_pid,
        row.sync_lease_until,
        row.sync_due_at,
        row.sync_last_completed_at,
    )


class DjangoServiceSynchronizationStorage:
    def read(self, service_id: UUID, actor_id: int) -> SynchronizationRead:
        try:
            row = authorized_services(actor_id).get(pk=service_id)
        except ServiceAccount.DoesNotExist as error:
            raise Missing("The service was not found.") from error
        return synchronization_read(row)

    def update(self, values: SynchronizationUpdate) -> SynchronizationRead:
        scoped_ids = authorized_services(values.actor_id).values("pk")
        changed = ServiceAccount.objects.filter(
            pk=values.service_id,
            pk__in=scoped_ids,
            owner_id=values.actor_id,
            sync_revision=values.expected_revision,
        ).update(
            sync_enabled=values.enabled,
            sync_interval_seconds=values.interval_seconds,
            sync_revision=F("sync_revision") + 1,
            sync_generation=F("sync_generation") + 1,
            sync_due_at=timezone.now(),
            sync_status=OperationStatus.QUEUED,
            sync_lease_token=None,
            sync_lease_until=None,
            sync_dispatched_at=None,
        )
        if changed != 1:
            raise Conflict("The synchronization settings changed. Reload before saving.")
        return self.read(values.service_id, values.actor_id)

    def claim(self, service_id: UUID, generation: int) -> SynchronizationClaim | None:
        try:
            current = ServiceAccount.objects.get(pk=service_id)
        except ServiceAccount.DoesNotExist as error:
            raise Missing("The service was not found.") from error
        now, token = timezone.now(), uuid4()
        available = ~Q(sync_status=OperationStatus.RUNNING) | Q(sync_lease_until__lt=now)
        changed = ServiceAccount.objects.filter(
            available,
            pk=service_id,
            sync_enabled=True,
            sync_generation=generation,
            sync_due_at__lte=now,
            status=OperationStatus.SUCCEEDED,
        ).update(
            sync_status=OperationStatus.RUNNING,
            sync_attempts=F("sync_attempts") + 1,
            sync_lease_token=token,
            sync_lease_until=now + timedelta(seconds=current.timeout_seconds + 30),
        )
        claim = None
        if changed:
            try:
                row = ServiceAccount.objects.select_related("xray").get(
                    pk=service_id,
                    sync_generation=generation,
                    sync_lease_token=token,
                    sync_status=OperationStatus.RUNNING,
                )
            except ServiceAccount.DoesNotExist:
                return None
            claim = SynchronizationClaim(service_read(row), synchronization_read(row), token)
        return claim

    def active(self, claim: SynchronizationClaim) -> bool:
        return ServiceAccount.objects.filter(
            pk=claim.service.id,
            owner_id=claim.service.owner_id,
            sync_enabled=True,
            sync_generation=claim.synchronization.generation,
            sync_lease_token=claim.token,
            sync_status=OperationStatus.RUNNING,
            sync_lease_until__gt=timezone.now(),
            status=OperationStatus.SUCCEEDED,
        ).exists()

    def finish(self, claim: SynchronizationClaim, error_code: str | None) -> None:
        now = timezone.now()
        ServiceAccount.objects.filter(
            pk=claim.service.id,
            owner_id=claim.service.owner_id,
            sync_generation=claim.synchronization.generation,
            sync_lease_token=claim.token,
            sync_status=OperationStatus.RUNNING,
            sync_lease_until__gt=now,
        ).update(
            sync_status=OperationStatus.SUCCEEDED if error_code is None else OperationStatus.FAILED,
            sync_generation=F("sync_generation") + 1,
            sync_error_code=error_code,
            sync_due_at=now + timedelta(seconds=claim.synchronization.interval_seconds),
            sync_last_completed_at=now,
            sync_worker_pid=os.getpid(),
            sync_lease_token=None,
            sync_lease_until=None,
            sync_dispatched_at=None,
        )

    def pending(self) -> tuple[SynchronizationDelivery, ...]:
        now = timezone.now()
        before = now - timedelta(seconds=settings.PAPILIO_OUTBOX_REDELIVERY_SECONDS)
        available = ~Q(sync_status=OperationStatus.RUNNING) | Q(sync_lease_until__lt=now)
        undelivered = Q(sync_dispatched_at__isnull=True) | Q(sync_dispatched_at__lt=before)
        rows = ServiceAccount.objects.filter(
            available,
            undelivered,
            sync_enabled=True,
            sync_due_at__lte=now,
            status=OperationStatus.SUCCEEDED,
        ).order_by("sync_due_at", "id")[: settings.PAPILIO_OUTBOX_BATCH_SIZE]
        return tuple(
            SynchronizationDelivery(row.id, row.sync_generation, row.timeout_seconds)
            for row in rows
        )

    def dispatched(self, deliveries: tuple[SynchronizationDelivery, ...]) -> None:
        if not deliveries:
            return
        identities = reduce(
            or_, (Q(pk=item.service_id, sync_generation=item.generation) for item in deliveries)
        )
        ServiceAccount.objects.filter(identities).update(sync_dispatched_at=timezone.now())
