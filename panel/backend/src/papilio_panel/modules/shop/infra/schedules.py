"""Native missing-only shop delivery schedule and current enablement facts."""

from typing import Any

from django.conf import settings
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from papilio_panel.config.celery import app
from papilio_panel.modules.jobs.domain import ScheduleKind
from papilio_panel.shared.errors import Missing

from ..domain import ShopTaskName


def initialize_shop(sender: object, **kwargs: Any) -> None:
    app.autodiscover_tasks(force=True)
    task = app.tasks[ShopTaskName.DISPATCH.value]
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=settings.PAPILIO_OUTBOX_INTERVAL_SECONDS, period=IntervalSchedule.SECONDS
    )
    PeriodicTask.objects.get_or_create(
        name=f"{settings.PAPILIO_NAMESPACE}.{ScheduleKind.SHOP_OUTBOX.value}",
        defaults={"task": task.name, "interval": interval, "queue": task.queue},
    )


class NativeShopSchedule:
    def enabled(self) -> bool:
        try:
            row = PeriodicTask.objects.get(
                name=f"{settings.PAPILIO_NAMESPACE}.{ScheduleKind.SHOP_OUTBOX.value}"
            )
        except PeriodicTask.DoesNotExist as error:
            raise Missing("The native shop delivery schedule is not initialized.") from error
        return row.enabled
