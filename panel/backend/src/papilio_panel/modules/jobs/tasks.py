"""Native Celery delivery, bounded diagnostics and worker heartbeats."""

from uuid import UUID

from celery import Task, shared_task
from django.db import OperationalError
from kombu.exceptions import OperationalError as BrokerError
from redis.exceptions import RedisError

from papilio_panel.config.queues import QueueKind, queue_name

from .domain import ProbeKind, TaskName
from .providers import execution_health, probe_execution, publications


@shared_task(
    bind=True,
    name=TaskName.IO_PROBE.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError, RedisError, ConnectionError),
    retry_backoff=True,
    max_retries=5,
)
def io_probe(self: Task, *, operation_id: str) -> None:
    outcome = probe_execution.execute(UUID(operation_id), ProbeKind.IO)
    if outcome.retry_after_seconds is not None:
        raise self.retry(countdown=outcome.retry_after_seconds, max_retries=None)


@shared_task(
    bind=True,
    name=TaskName.CPU_PROBE.value,
    queue=queue_name(QueueKind.CPU),
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def cpu_probe(self: Task, *, operation_id: str) -> None:
    outcome = probe_execution.execute(UUID(operation_id), ProbeKind.CPU)
    if outcome.retry_after_seconds is not None:
        raise self.retry(countdown=outcome.retry_after_seconds, max_retries=None)


@shared_task(
    name=TaskName.DISPATCH.value,
    queue=queue_name(QueueKind.IO),
    autoretry_for=(OperationalError, BrokerError),
    retry_backoff=True,
    max_retries=5,
)
def dispatch_outbox() -> None:
    publications.dispatch()


@shared_task(bind=True, name=TaskName.IO_HEARTBEAT.value, queue=queue_name(QueueKind.IO))
def io_heartbeat(self: Task) -> None:
    execution_health.record(QueueKind.IO.value, self.request.delivery_info["routing_key"])


@shared_task(bind=True, name=TaskName.CPU_HEARTBEAT.value, queue=queue_name(QueueKind.CPU))
def cpu_heartbeat(self: Task) -> None:
    execution_health.record(QueueKind.CPU.value, self.request.delivery_info["routing_key"])
