"""Native transactional decision events and bounded durable delivery facts."""

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from papilio_panel.shared.errors import Missing

from ..domain import DecisionAction, PaymentEventDelivery, PaymentEventOutcome, PaymentEventRead
from ..models import PaymentDecisionEvent


class DjangoPaymentEventStorage:
    def append(self, decision_id: UUID) -> None:
        PaymentDecisionEvent.objects.get_or_create(decision_id=decision_id)

    def read(self, event_id: UUID, actor_id: int) -> PaymentEventRead:
        try:
            row = PaymentDecisionEvent.objects.select_related("decision__invoice").get(
                pk=event_id,
                decision__actor_id=actor_id,
                decision__invoice__owner_id=actor_id,
                decision__invoice__customer__owner_id=actor_id,
            )
        except PaymentDecisionEvent.DoesNotExist as error:
            raise Missing("The payment decision event was not found for this owner.") from error
        return PaymentEventRead(
            row.id,
            row.decision_id,
            row.decision.invoice_id,
            row.decision.actor_id,
            DecisionAction(row.decision.action),
            row.created_at,
            row.processed_at,
            PaymentEventOutcome(row.outcome) if row.outcome is not None else None,
        )

    def acknowledge(self, event_id: UUID, outcome: PaymentEventOutcome) -> None:
        PaymentDecisionEvent.objects.filter(pk=event_id, processed_at__isnull=True).update(
            processed_at=Coalesce("processed_at", timezone.now()),
            outcome=outcome,
        )

    def pending(self) -> tuple[PaymentEventDelivery, ...]:
        before = timezone.now() - timedelta(seconds=settings.PAPILIO_OUTBOX_REDELIVERY_SECONDS)
        rows = (
            PaymentDecisionEvent.objects.filter(
                Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=before),
                processed_at__isnull=True,
                decision__actor__is_active=True,
                decision__actor__is_staff=True,
                decision__actor__is_superuser=True,
            )
            .select_related("decision")
            .order_by("created_at", "id")[: settings.PAPILIO_OUTBOX_BATCH_SIZE]
        )
        return tuple(PaymentEventDelivery(row.id, row.decision.actor_id) for row in rows)

    def dispatched(self, deliveries: tuple[PaymentEventDelivery, ...]) -> None:
        PaymentDecisionEvent.objects.filter(pk__in=[item.id for item in deliveries]).update(
            dispatched_at=timezone.now()
        )
