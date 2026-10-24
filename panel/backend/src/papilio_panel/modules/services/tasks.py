"""Native I/O task entrypoints for service provisioning and durable delivery."""

from uuid import UUID

from celery import Task, shared_task
from django.db import OperationalError
from kombu.exceptions import OperationalError as BrokerError
from rest_framework.serializers import IntegerField

from papilio_panel.config.queues import QueueKind, queue_name
from papilio_panel.shared.errors import ApplicationError

from .domain import ServiceTaskName
from .providers import (
    execution,
    publications,
    synchronization_execution,
    synchronization_publications,
)
from .synchronization_contracts import SynchronizationTaskName


@shared_task(
    bind=True,
    name=ServiceTaskName.PROVISION.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def provision_service(self: Task, *, service_id: str) -> None:
    result = execution.provision(UUID(service_id))
    if result.retry_after_seconds is not None:
        raise self.retry(countdown=result.retry_after_seconds, max_retries=None)


@shared_task(
    name=ServiceTaskName.DISPATCH.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError, BrokerError),
    retry_backoff=True,
    max_retries=5,
)
def dispatch_outbox() -> None:
    publications.dispatch()


@shared_task(
    name=SynchronizationTaskName.SYNCHRONIZE.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def synchronize_service(*, service_id: str, generation: str) -> None:
    work_generation = IntegerField(min_value=1, max_value=9223372036854775807).run_validation(
        generation
    )
    claim = synchronization_execution.begin(UUID(service_id), work_generation)
    if claim is not None:
        try:
            synchronization_execution.apply(claim)
        except ApplicationError as error:
            synchronization_execution.reject(claim, error.code)


@shared_task(
    name=SynchronizationTaskName.DISPATCH.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError, BrokerError),
    retry_backoff=True,
    max_retries=5,
)
def dispatch_synchronization() -> None:
    synchronization_publications.dispatch()
