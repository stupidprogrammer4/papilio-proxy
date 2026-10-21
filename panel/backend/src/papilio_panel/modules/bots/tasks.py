"""Native scheduled I/O task; credentials never enter broker arguments."""

from uuid import UUID

from celery import shared_task
from django.db import OperationalError

from papilio_panel.config.queues import QueueKind, queue_name

from .domain import BotTaskName
from .providers import polling


@shared_task(
    name=BotTaskName.POLL.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def poll(*, bot_id: str) -> None:
    polling.poll(UUID(bot_id))
