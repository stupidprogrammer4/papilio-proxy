"""Deliver persisted node work through the native broker publisher."""

from ..interfaces import NodePublisher, NodeStorage


class NodePublications:
    def __init__(self, storage: NodeStorage, publisher: NodePublisher) -> None:
        self.storage = storage
        self.publisher = publisher

    def dispatch(self) -> None:
        deliveries = self.storage.pending_deliveries()
        if deliveries:
            self.publisher.publish(deliveries)
            self.storage.mark_dispatched(deliveries)
