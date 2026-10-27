"""Publish persisted node operations using native Celery signatures and routing."""

from celery.canvas import Signature, group

from ..domain import NodeTaskName, NodeWorkKind, WorkDelivery


class NativeNodePublisher:
    def publish(self, deliveries: tuple[WorkDelivery, ...]) -> None:
        signatures = (
            Signature(
                {
                    NodeWorkKind.ISSUE: NodeTaskName.ISSUE.value,
                    NodeWorkKind.CHECK: NodeTaskName.CHECK.value,
                    NodeWorkKind.TRAFFIC: NodeTaskName.TRAFFIC.value,
                }[item.kind],
                kwargs={"operation_id": str(item.operation_id)},
            ).set(
                task_id=str(item.operation_id),
                time_limit=item.timeout_seconds,
                soft_time_limit=max(1, item.timeout_seconds - 5),
            )
            for item in deliveries
        )
        group(signatures).apply_async()
