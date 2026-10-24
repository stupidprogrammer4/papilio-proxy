"""Initialize the missing service delivery schedule without resetting operator choices."""

from typing import Any

from django.conf import settings
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from papilio_panel.config.celery import app
from papilio_panel.modules.jobs.domain import ScheduleKind
from papilio_panel.shared.errors import Missing

from ..domain import ServiceTaskName
from ..synchronization_contracts import SynchronizationTaskName


def initialize_services(sender: object, **kwargs: Any) -> None:
    app.autodiscover_tasks(force=True)
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=settings.PAPILIO_OUTBOX_INTERVAL_SECONDS, period=IntervalSchedule.SECONDS
    )
    definitions = (
        (ScheduleKind.SERVICE_OUTBOX, ServiceTaskName.DISPATCH.value),
        (ScheduleKind.SERVICE_SYNCHRONIZATION, SynchronizationTaskName.DISPATCH.value),
    )
    for kind, name in definitions:
        task = app.tasks[name]
        PeriodicTask.objects.get_or_create(
            name=f"{settings.PAPILIO_NAMESPACE}.{kind.value}",
            defaults={"task": task.name, "interval": interval, "queue": task.queue},
        )


class NativeServiceSchedule:
    def __init__(self, kind: ScheduleKind = ScheduleKind.SERVICE_OUTBOX) -> None:
        self.kind = kind

    def enabled(self) -> bool:
        name = f"{settings.PAPILIO_NAMESPACE}.{self.kind.value}"
        try:
            row = PeriodicTask.objects.get(name=name)
        except PeriodicTask.DoesNotExist as error:
            raise Missing("The service delivery schedule is not initialized.") from error
        return row.enabled
