"""Native IO-worker entrypoints own technical retries and error translation."""

from uuid import UUID

from celery import Task, shared_task
from django.db import OperationalError
from kombu.exceptions import OperationalError as BrokerError

from papilio_panel.config.queues import QueueKind, queue_name
from papilio_panel.shared.errors import ApplicationError

from .domain import LocalTaskName
from .providers import execution, publications


@shared_task(
    bind=True,
    name=LocalTaskName.PREPARE.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def prepare_local_node(self: Task, *, operation_id: str) -> None:
    attempt = execution.begin(UUID(operation_id))
    if attempt.retry_after_seconds is not None:
        raise self.retry(countdown=attempt.retry_after_seconds, max_retries=None)
    if attempt.claim is not None:
        try:
            execution.prepare(attempt.claim)
        except ApplicationError as error:
            execution.reject(attempt.claim, error.code)
        except OSError:
            execution.reject(attempt.claim, "local_files_unavailable", retryable=True)


@shared_task(
    name=LocalTaskName.DISPATCH.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError, BrokerError),
    retry_backoff=True,
    max_retries=5,
)
def dispatch_local_node() -> None:
    publications.dispatch()
