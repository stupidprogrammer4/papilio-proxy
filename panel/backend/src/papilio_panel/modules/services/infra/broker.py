"""Deliver persisted service identities using native Celery signatures and groups."""

from celery.canvas import Signature, group

from ..domain import ServiceDelivery, ServiceTaskName
from ..synchronization_contracts import SynchronizationDelivery, SynchronizationTaskName


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


class NativeServiceSynchronizationPublisher:
    def publish(self, deliveries: tuple[SynchronizationDelivery, ...]) -> None:
        signatures = (
            Signature(
                SynchronizationTaskName.SYNCHRONIZE.value,
                kwargs={"service_id": str(item.service_id), "generation": str(item.generation)},
            ).set(
                task_id=f"{item.service_id}:{item.generation}",
                time_limit=item.timeout_seconds,
                soft_time_limit=max(1, item.timeout_seconds - 5),
            )
            for item in deliveries
        )
        group(signatures).apply_async()
