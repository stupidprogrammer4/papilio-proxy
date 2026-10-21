"""Publish committed operation requests independently of business transactions."""

from ..interfaces import DeliveryPublisher, OperationStorage


class OperationPublications:
    def __init__(self, storage: OperationStorage, publisher: DeliveryPublisher) -> None:
        self.storage = storage
        self.publisher = publisher

    def dispatch(self) -> None:
        deliveries = self.storage.pending_deliveries()
        if deliveries:
            self.publisher.publish(deliveries)
            self.storage.mark_dispatched(deliveries)
