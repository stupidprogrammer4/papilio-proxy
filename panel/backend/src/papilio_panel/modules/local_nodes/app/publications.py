"""Deliver current durable local work without claiming broker/DB atomicity."""

from ..interfaces import LocalDeliverySchedule, LocalPublisher, LocalWorkStorage


class LocalPublications:
    def __init__(
        self, storage: LocalWorkStorage, publisher: LocalPublisher, schedule: LocalDeliverySchedule
    ) -> None:
        self.storage, self.publisher, self.schedule = storage, publisher, schedule

    def dispatch(self) -> None:
        if not self.schedule.enabled():
            return
        delivery = self.storage.pending()
        if delivery is not None:
            self.publisher.publish(delivery)
            self.storage.dispatched(delivery)
