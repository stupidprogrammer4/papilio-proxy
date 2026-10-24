"""Native I/O entrypoints for shop events and private outgoing messages."""

from uuid import UUID

from celery import Task, shared_task
from django.db import OperationalError
from kombu.exceptions import OperationalError as BrokerError
from rest_framework.exceptions import ValidationError

from papilio_panel.config.queues import QueueKind, queue_name
from papilio_panel.shared.errors import ApplicationError, Conflict

from .domain import ReceiptDownloadFailure, ShopTaskName
from .providers import execution, publications, sending, settlements


@shared_task(
    name=ShopTaskName.SETTLEMENT.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError, Conflict),
    retry_backoff=True,
    max_retries=5,
)
def settlement(*, event_id: str, actor_id: int) -> None:
    settlements.notify(UUID(event_id), actor_id)


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
    bind=True,
    name=ShopTaskName.PROCESS.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    max_retries=None,
)
def process(self: Task, *, work_id: str) -> None:
    claim = execution.begin(UUID(work_id))
    if claim is not None:
        try:
            prepared = execution.prepare(claim)
            execution.process(claim, prepared)
        except ReceiptDownloadFailure as error:
            retry = execution.retry_receipt(claim, error)
            if retry.retry_after_seconds is not None:
                raise self.retry(countdown=retry.retry_after_seconds) from None
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
