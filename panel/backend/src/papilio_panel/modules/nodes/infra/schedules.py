"""Seed missing native metadata/schedules without replacing operator choices."""

from typing import Any

from django.conf import settings
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from papilio_panel.config.celery import app
from papilio_panel.modules.jobs.domain import ScheduleKind

from ..domain import NodeTaskName
from ..models import DeploymentIdentity


def initialize_nodes(sender: object, **kwargs: Any) -> None:
    DeploymentIdentity.objects.get_or_create(pk=1)
    app.autodiscover_tasks(force=True)
    task = app.tasks[NodeTaskName.DISPATCH.value]
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=settings.PAPILIO_OUTBOX_INTERVAL_SECONDS,
        period=IntervalSchedule.SECONDS,
    )
    PeriodicTask.objects.get_or_create(
        name=f"{settings.PAPILIO_NAMESPACE}.{ScheduleKind.NODE_OUTBOX.value}",
        defaults={"task": task.name, "interval": interval, "queue": task.queue},
    )
