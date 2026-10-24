"""Publish the single physical runtime's work with native Celery routing."""

from celery.canvas import Signature

from ..domain import LocalDelivery, LocalTaskName


class NativeLocalPublisher:
    def publish(self, delivery: LocalDelivery) -> None:
        Signature(
            LocalTaskName.PREPARE.value, kwargs={"operation_id": str(delivery.operation_id)}
        ).set(
            task_id=str(delivery.operation_id),
            time_limit=delivery.timeout_seconds,
            soft_time_limit=max(1, delivery.timeout_seconds - 5),
        ).apply_async()
