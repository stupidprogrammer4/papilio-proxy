"""Native set-based inbox discovery and per-event conditional processing leases."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from papilio_panel.shared.errors import Conflict, Missing

from ..domain import WorkClaim, WorkDelivery, WorkRead, WorkState
from ..models import InboxWork, ShopConfiguration


class DjangoShopWorkStorage:
    def discover(self) -> None:
        event_ids = (
            ShopConfiguration.objects.filter(
                enabled=True,
                bot__periodic_task__enabled=True,
                bot__telegraminbox__processed_at__isnull=True,
                bot__telegraminbox__shop_work__isnull=True,
            )
            .exclude(bot__telegraminbox__id__isnull=True)
            .order_by("bot__telegraminbox__received_at", "bot__telegraminbox__id")
            .values_list("bot__telegraminbox__id", flat=True)[: settings.PAPILIO_OUTBOX_BATCH_SIZE]
        )
        InboxWork.objects.bulk_create(
            [InboxWork(event_id=event_id) for event_id in event_ids], ignore_conflicts=True
        )

    def read(self, work_id: UUID) -> WorkRead:
        try:
            row = InboxWork.objects.get(pk=work_id)
        except InboxWork.DoesNotExist as error:
            raise Missing("The bot conversation work was not found.") from error
        return WorkRead(row.id, row.event_id, WorkState(row.status))

    def claim(self, work_id: UUID, lease_seconds: int) -> UUID | None:
        now, token = timezone.now(), uuid4()
        eligible = Q(status=WorkState.QUEUED) | Q(status=WorkState.RUNNING, lease_until__lt=now)
        updated = InboxWork.objects.filter(eligible, pk=work_id).update(
            status=WorkState.RUNNING,
            lease_token=token,
            lease_until=now + timedelta(seconds=lease_seconds),
        )
        return token if updated else None

    def complete(self, claim: WorkClaim, error_code: str | None = None) -> None:
        updated = InboxWork.objects.filter(
            pk=claim.id, event_id=claim.event.id, lease_token=claim.token, status=WorkState.RUNNING
        ).update(
            status=WorkState.DONE if error_code is None else WorkState.FAILED,
            completed_at=timezone.now(),
            error_code=error_code,
            lease_token=None,
            lease_until=None,
            worker_pid=os.getpid(),
        )
        if updated != 1:
            raise Conflict("The bot conversation lease changed before its effects committed.")

    def release(self, claim: WorkClaim) -> None:
        updated = InboxWork.objects.filter(
            pk=claim.id, event_id=claim.event.id, lease_token=claim.token, status=WorkState.RUNNING
        ).update(status=WorkState.QUEUED, lease_token=None, lease_until=None, dispatched_at=None)
        if updated != 1:
            raise Conflict("The bot conversation lease changed before it could be released.")

    def pending(self) -> tuple[WorkDelivery, ...]:
        now = timezone.now()
        before = now - timedelta(seconds=settings.PAPILIO_OUTBOX_REDELIVERY_SECONDS)
        pending = Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=before)
        active = Q(status=WorkState.QUEUED) | Q(status=WorkState.RUNNING, lease_until__lt=now)
        rows = (
            InboxWork.objects.filter(
                pending,
                active,
                event__bot__shop_configuration__enabled=True,
                event__bot__periodic_task__enabled=True,
            )
            .select_related("event__bot")
            .order_by("event__received_at", "id")[: settings.PAPILIO_OUTBOX_BATCH_SIZE]
        )
        return tuple(
            WorkDelivery(row.id, 3 * row.event.bot.http_timeout_seconds + 60) for row in rows
        )

    def dispatched(self, deliveries: tuple[WorkDelivery, ...]) -> None:
        InboxWork.objects.filter(pk__in=[item.id for item in deliveries]).update(
            dispatched_at=timezone.now()
        )
