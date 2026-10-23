"""Authorize decision-event consumers while preserving native outbox replay."""

from uuid import UUID

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import InvalidInput

from ..domain import PaymentEventDelivery, PaymentEventOutcome, PaymentEventRead
from ..interfaces import PaymentEventStorage


class PaymentDecisionEvents:
    def __init__(self, storage: PaymentEventStorage, access: AdminAccessCapability) -> None:
        self.storage = storage
        self.access = access

    def read(self, event_id: UUID, actor_id: int) -> PaymentEventRead:
        self.access.authorize_owner(actor_id)
        result = self.storage.read(event_id, actor_id)
        return result

    def acknowledge(self, event_id: UUID, actor_id: int, outcome: PaymentEventOutcome) -> None:
        self.read(event_id, actor_id)
        if not isinstance(outcome, PaymentEventOutcome):
            raise InvalidInput("Choose a declared payment event outcome.")
        self.storage.acknowledge(event_id, outcome)

    def pending(self) -> tuple[PaymentEventDelivery, ...]:
        result = self.storage.pending()
        return result

    def dispatched(self, deliveries: tuple[PaymentEventDelivery, ...]) -> None:
        self.storage.dispatched(deliveries)
