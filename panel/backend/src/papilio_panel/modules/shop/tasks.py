"""Native I/O entrypoints for shop events and private outgoing messages."""

from uuid import UUID

from celery import Task, shared_task
from django.db import OperationalError
from kombu.exceptions import OperationalError as BrokerError
from rest_framework.exceptions import ValidationError

from papilio_panel.config.queues import QueueKind, queue_name
from papilio_panel.shared.errors import ApplicationError

from .domain import ShopTaskName
from .providers import execution, publications, sending


@shared_task(
    name=ShopTaskName.DISPATCH.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError, BrokerError),
    retry_backoff=True,
    max_retries=5,
)
def dispatch() -> None:
    publications.dispatch()


@shared_task(
    name=ShopTaskName.PROCESS.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def process(*, work_id: str) -> None:
    claim = execution.begin(UUID(work_id))
    if claim is not None:
        try:
            execution.process(claim)
        except ApplicationError as error:
            execution.fail(claim, error.code, str(error))
        except ValidationError:
            execution.fail(claim, "invalid_input", "Check the command arguments and try again.")


@shared_task(
    bind=True,
    name=ShopTaskName.SEND.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def send(self: Task, *, message_id: str) -> None:
    claim = sending.begin(UUID(message_id))
    if claim is not None:
        try:
            outcome = sending.send(claim)
        except ApplicationError as error:
            outcome = sending.fail(claim, error.code)
        if outcome.retry_after_seconds is not None:
            raise self.retry(countdown=outcome.retry_after_seconds, max_retries=None)
