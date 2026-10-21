"""Store actual worker delivery facts and read native dependency readiness."""

import os
import socket
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connection
from django.utils import timezone
from redis.exceptions import RedisError

from papilio_panel.config.queues import QueueKind, queue_name

from ..domain import Readiness, WorkerObservation
from ..models import WorkerHeartbeat


def record_heartbeat(role: str, actual_queue: str) -> None:
    WorkerHeartbeat.objects.update_or_create(
        role=role,
        defaults={
            "queue": actual_queue,
            "worker_pid": os.getpid(),
            "worker_host": socket.gethostname(),
            "observed_at": timezone.now(),
        },
    )


def worker_observations() -> tuple[WorkerObservation, ...]:
    return tuple(
        WorkerObservation(
            role=row.role,
            queue=row.queue,
            worker_host=row.worker_host,
            worker_pid=row.worker_pid,
            observed_at=row.observed_at,
        )
        for row in WorkerHeartbeat.objects.all().order_by("role")
    )


def readiness() -> Readiness:
    database_ok = False
    cache_ok = False
    workers_ok = False
    try:
        connection.ensure_connection()
        database_ok = True
        threshold = timezone.now() - timedelta(seconds=settings.PAPILIO_HEARTBEAT_MAX_AGE_SECONDS)
        fresh = set(
            WorkerHeartbeat.objects.filter(observed_at__gte=threshold).values_list(
                "queue", flat=True
            )
        )
        workers_ok = {queue_name(QueueKind.IO), queue_name(QueueKind.CPU)} <= fresh
    except DatabaseError:
        connection.close()
    try:
        cache.get("readiness")
        cache_ok = True
    except (RedisError, OSError):
        cache_ok = False
    return Readiness(database=database_ok, cache=cache_ok, workers=workers_ok)


class DjangoExecutionHealthStorage:
    def readiness(self) -> Readiness:
        facts = readiness()
        return facts

    def observations(self) -> tuple[WorkerObservation, ...]:
        facts = worker_observations()
        return facts

    def record(self, role: str, actual_queue: str) -> None:
        record_heartbeat(role, actual_queue)
