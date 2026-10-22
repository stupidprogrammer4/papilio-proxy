"""Initialize the missing service delivery schedule without resetting operator choices."""

from typing import Any

from django.conf import settings
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from papilio_panel.config.celery import app
from papilio_panel.modules.jobs.domain import ScheduleKind
from papilio_panel.shared.errors import Missing

from ..domain import ServiceTaskName


def initialize_services(sender: object, **kwargs: Any) -> None:
    app.autodiscover_tasks(force=True)
    task = app.tasks[ServiceTaskName.DISPATCH.value]
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=settings.PAPILIO_OUTBOX_INTERVAL_SECONDS, period=IntervalSchedule.SECONDS
    )
    PeriodicTask.objects.get_or_create(
        name=f"{settings.PAPILIO_NAMESPACE}.{ScheduleKind.SERVICE_OUTBOX.value}",
        defaults={"task": task.name, "interval": interval, "queue": task.queue},
    )


class NativeServiceSchedule:
    def enabled(self) -> bool:
        name = f"{settings.PAPILIO_NAMESPACE}.{ScheduleKind.SERVICE_OUTBOX.value}"
        try:
            row = PeriodicTask.objects.get(name=name)
        except PeriodicTask.DoesNotExist as error:
            raise Missing("The service delivery schedule is not initialized.") from error
        return row.enabled
