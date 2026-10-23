"""Publish independent durable conversation and reply identities using native tasks."""

from ..interfaces import ShopDeliverySchedule, ShopMessageStorage, ShopPublisher, ShopWorkStorage


class ShopPublications:
    def __init__(
        self,
        work: ShopWorkStorage,
        messages: ShopMessageStorage,
        publisher: ShopPublisher,
        schedule: ShopDeliverySchedule,
    ) -> None:
        self.work = work
        self.messages = messages
        self.publisher = publisher
        self.schedule = schedule

    def dispatch(self) -> None:
        if not self.schedule.enabled():
            return
        self.work.discover()
        incoming = self.work.pending()
        if incoming:
            self.publisher.work(incoming)
            self.work.dispatched(incoming)
        outgoing = self.messages.pending()
        if outgoing:
            self.publisher.messages(outgoing)
            self.messages.dispatched(outgoing)
