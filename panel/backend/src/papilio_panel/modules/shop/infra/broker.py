"""Native Celery group publication of bounded independent persisted work identities."""

from celery.canvas import Signature, group

from papilio_panel.modules.payments.domain import PaymentEventDelivery

from ..domain import ShopTaskName, WorkDelivery


class NativeShopPublisher:
    def settlements(self, deliveries: tuple[PaymentEventDelivery, ...]) -> None:
        signatures = (
            Signature(
                ShopTaskName.SETTLEMENT.value,
                kwargs={"event_id": str(item.id), "actor_id": item.owner_id},
            ).set(task_id=str(item.id))
            for item in deliveries
        )
        group(signatures).apply_async()

    def work(self, deliveries: tuple[WorkDelivery, ...]) -> None:
        signatures = (
            Signature(ShopTaskName.PROCESS.value, kwargs={"work_id": str(item.id)}).set(
                task_id=str(item.id),
                time_limit=item.timeout_seconds,
                soft_time_limit=max(1, item.timeout_seconds - 5),
            )
            for item in deliveries
        )
        group(signatures).apply_async()

    def messages(self, deliveries: tuple[WorkDelivery, ...]) -> None:
        signatures = (
            Signature(ShopTaskName.SEND.value, kwargs={"message_id": str(item.id)}).set(
                task_id=str(item.id),
                time_limit=item.timeout_seconds,
                soft_time_limit=max(1, item.timeout_seconds - 5),
            )
            for item in deliveries
        )
        group(signatures).apply_async()
