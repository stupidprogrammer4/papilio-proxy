"""Native I/O task entrypoints for service provisioning and durable delivery."""

from uuid import UUID

from celery import Task, shared_task
from django.db import OperationalError
from kombu.exceptions import OperationalError as BrokerError

from papilio_panel.config.queues import QueueKind, queue_name

from .domain import ServiceTaskName
from .providers import execution, publications


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
