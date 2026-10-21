"""Publish independent persisted messages with native Celery canvas APIs."""

from celery.canvas import Signature, group

from ..domain import Delivery, ProbeKind, TaskName


class CeleryDeliveryPublisher:
    def publish(self, deliveries: tuple[Delivery, ...]) -> None:
        signatures = (
            Signature(
                TaskName.IO_PROBE.value
                if delivery.kind == ProbeKind.IO
                else TaskName.CPU_PROBE.value,
                kwargs={"operation_id": str(delivery.operation_id)},
            ).set(task_id=str(delivery.operation_id))
            for delivery in deliveries
        )
        group(signatures).apply_async()
