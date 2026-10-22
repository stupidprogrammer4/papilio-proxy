"""Deliver persisted service identities using native Celery signatures and groups."""

from celery.canvas import Signature, group

from ..domain import ServiceDelivery, ServiceTaskName


class NativeServicePublisher:
    def publish(self, deliveries: tuple[ServiceDelivery, ...]) -> None:
        signatures = (
            Signature(
                ServiceTaskName.PROVISION.value, kwargs={"service_id": str(item.service_id)}
            ).set(
                task_id=str(item.service_id),
                time_limit=item.timeout_seconds,
                soft_time_limit=max(1, item.timeout_seconds - 5),
            )
            for item in deliveries
        )
        group(signatures).apply_async()
