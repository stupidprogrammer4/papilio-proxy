"""Native CPU/IO node task entrypoints with technical retry ownership."""

from uuid import UUID

from celery import Task, shared_task
from django.db import OperationalError
from kombu.exceptions import OperationalError as BrokerError

from papilio_panel.config.queues import QueueKind, queue_name

from .domain import NodeTaskName
from .providers import execution, publications


@shared_task(
    bind=True,
    name=NodeTaskName.ISSUE.value,
    queue=queue_name(QueueKind.CPU),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def issue_credentials(self: Task, *, operation_id: str) -> None:
    outcome = execution.issue(UUID(operation_id))
    if outcome.retry_after_seconds is not None:
        raise self.retry(countdown=outcome.retry_after_seconds, max_retries=None)


@shared_task(
    bind=True,
    name=NodeTaskName.CHECK.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def check_connection(self: Task, *, operation_id: str) -> None:
    outcome = execution.check(UUID(operation_id))
    if outcome.retry_after_seconds is not None:
        raise self.retry(countdown=outcome.retry_after_seconds, max_retries=None)


@shared_task(
    name=NodeTaskName.DISPATCH.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError, BrokerError),
    retry_backoff=True,
    max_retries=5,
)
def dispatch_outbox() -> None:
    publications.dispatch()
