"""Deliver committed service work independently of the database transaction."""

from ..interfaces import ServiceDeliverySchedule, ServicePublisher, ServiceStorage


class ServicePublications:
    def __init__(
        self,
        storage: ServiceStorage,
        publisher: ServicePublisher,
        schedule: ServiceDeliverySchedule,
    ) -> None:
        self.storage = storage
        self.publisher = publisher
        self.schedule = schedule

    def dispatch(self) -> None:
        if not self.schedule.enabled():
            return
        deliveries = self.storage.pending_deliveries()
        if deliveries:
            self.publisher.publish(deliveries)
            self.storage.mark_dispatched(deliveries)
