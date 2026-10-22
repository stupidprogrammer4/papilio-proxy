"""Native atomic service aggregate and durable outbox persistence."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from papilio_panel.shared.credentials import credential_cipher
from papilio_panel.shared.errors import Missing
from papilio_panel.shared.operations import OperationStatus

from ..domain import (
    ServiceClaim,
    ServiceCreate,
    ServiceCreation,
    ServiceDefinition,
    ServiceDelivery,
)
from ..models import ServiceAccount, ServiceOutbox, XrayService
from .readers import DjangoServiceReader, credential_read, service_read


class DjangoServiceStorage(DjangoServiceReader):
    def create(
        self, values: ServiceCreate, user_level: int, timeout_seconds: int
    ) -> ServiceCreation:
        selected = values.definition
        row, created = ServiceAccount.objects.get_or_create(
            owner_id=values.actor_id,
            request_key=values.request_key,
            defaults={
                "core_id": selected.core_id,
                "name": selected.name,
                "timeout_seconds": timeout_seconds,
            },
        )
        if created:
            identifier = selected.identifier or uuid4()
            ciphertext = credential_cipher().encrypt(str(identifier).encode())
            XrayService.objects.create(
                service=row,
                inbound_id=selected.inbound_id,
                credential_ciphertext=ciphertext,
                credential_supplied=selected.identifier is not None,
                requested_level=selected.user_level,
                level=user_level,
                email=f"papilio-{row.id.hex}",
            )
        row = ServiceAccount.objects.select_related("xray").get(pk=row.id)
        original = ServiceDefinition(
            row.name,
            row.core_id,
            row.xray.inbound_id,
            row.xray.requested_level,
            credential_read(row).identifier if row.xray.credential_supplied else None,
        )
        return ServiceCreation(service_read(row), original, created)

    def add_outbox(self, service_id: UUID) -> None:
        ServiceOutbox.objects.create(service_id=service_id)

    def claim(self, service_id: UUID) -> ServiceClaim:
        now, token = timezone.now(), uuid4()
        eligible = Q(status=OperationStatus.QUEUED) | Q(
            status=OperationStatus.RUNNING, lease_until__lt=now
        )
        maximum = settings.PAPILIO_OPERATION_MAX_ATTEMPTS
        ServiceAccount.objects.filter(eligible, pk=service_id, attempts__gte=maximum).update(
            status=OperationStatus.FAILED,
            error_code="retry_exhausted",
            completed_at=now,
            lease_token=None,
            lease_until=None,
        )
        try:
            current = ServiceAccount.objects.get(pk=service_id)
        except ServiceAccount.DoesNotExist as error:
            raise Missing("The service was not found.") from error
        changed = ServiceAccount.objects.filter(
            eligible, pk=service_id, attempts__lt=maximum
        ).update(
            status=OperationStatus.RUNNING,
            attempts=F("attempts") + 1,
            lease_token=token,
            lease_until=now + timedelta(seconds=current.timeout_seconds + 30),
        )
        row = ServiceAccount.objects.select_related("xray").get(pk=service_id)
        return ServiceClaim(service_read(row), token if changed else None)

    def finish(self, claim: ServiceClaim, error_code: str | None) -> None:
        ServiceAccount.objects.filter(
            pk=claim.service.id,
            owner_id=claim.service.owner_id,
            status=OperationStatus.RUNNING,
            lease_token=claim.token,
        ).update(
            status=OperationStatus.SUCCEEDED if error_code is None else OperationStatus.FAILED,
            error_code=error_code,
            worker_pid=os.getpid(),
            lease_until=None,
            lease_token=None,
            completed_at=timezone.now(),
        )

    def pending_deliveries(self) -> tuple[ServiceDelivery, ...]:
        now = timezone.now()
        before = now - timedelta(seconds=settings.PAPILIO_OUTBOX_REDELIVERY_SECONDS)
        pending = Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=before)
        active = Q(service__status=OperationStatus.QUEUED) | Q(
            service__status=OperationStatus.RUNNING, service__lease_until__lt=now
        )
        rows = (
            ServiceOutbox.objects.filter(pending, active)
            .select_related("service")
            .order_by("service__created_at", "service_id")[: settings.PAPILIO_OUTBOX_BATCH_SIZE]
        )
        return tuple(ServiceDelivery(row.service_id, row.service.timeout_seconds) for row in rows)

    def mark_dispatched(self, deliveries: tuple[ServiceDelivery, ...]) -> None:
        ServiceOutbox.objects.filter(
            service_id__in=[item.service_id for item in deliveries]
        ).update(dispatched_at=timezone.now())
