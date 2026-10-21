"""Initialize native Beat records only after migrations and preserve operator edits."""

from typing import Any

from django.conf import settings
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask, PeriodicTasks

from papilio_panel.config.celery import app
from papilio_panel.shared.errors import Conflict

from ..domain import ScheduleKind, ScheduleRead, ScheduleUpdate, TaskName


def initialize_schedules(sender: object, **kwargs: Any) -> None:
    app.autodiscover_tasks(force=True)
    definitions = (
        (ScheduleKind.IO_HEARTBEAT, TaskName.IO_HEARTBEAT, settings.PAPILIO_HEARTBEAT_SECONDS),
        (ScheduleKind.CPU_HEARTBEAT, TaskName.CPU_HEARTBEAT, settings.PAPILIO_HEARTBEAT_SECONDS),
        (ScheduleKind.OUTBOX, TaskName.DISPATCH, settings.PAPILIO_OUTBOX_INTERVAL_SECONDS),
    )
    for kind, task_name, seconds in definitions:
        task = app.tasks[task_name.value]
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=seconds, period=IntervalSchedule.SECONDS
        )
        PeriodicTask.objects.get_or_create(
            name=f"{settings.PAPILIO_NAMESPACE}.{kind.value}",
            defaults={"task": task.name, "interval": interval, "queue": task.queue},
        )


def schedule_read(row: PeriodicTask) -> ScheduleRead:
    interval = row.interval
    if interval is None or interval.period != IntervalSchedule.SECONDS:
        raise Conflict("This managed schedule requires an interval measured in seconds.")
    return ScheduleRead(
        key=ScheduleKind(row.name.removeprefix(settings.PAPILIO_NAMESPACE + ".")),
        enabled=row.enabled,
        interval_seconds=interval.every,
        changed_at=row.date_changed,
    )


class DjangoScheduleStorage:
    def read_all(self) -> tuple[ScheduleRead, ...]:
        names = tuple(f"{settings.PAPILIO_NAMESPACE}.{key.value}" for key in ScheduleKind)
        rows = (
            PeriodicTask.objects.filter(name__in=names).select_related("interval").order_by("name")
        )
        return tuple(schedule_read(row) for row in rows)

    def update(self, values: ScheduleUpdate) -> ScheduleRead:
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=values.interval_seconds, period=IntervalSchedule.SECONDS
        )
        name = f"{settings.PAPILIO_NAMESPACE}.{values.key.value}"
        changed = PeriodicTask.objects.filter(
            name=name, date_changed=values.expected_changed_at
        ).update(interval=interval, enabled=values.enabled, date_changed=timezone.now())
        if changed != 1:
            raise Conflict("The schedule changed. Reload it before saving.")
        PeriodicTasks.update_changed()
        row = PeriodicTask.objects.select_related("interval").get(name=name)
        return schedule_read(row)
