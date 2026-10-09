from papilio_tasks.infra.taskiq.sources.backends.redis import RedisSource
from taskiq.decor import AsyncTaskiqDecoratedTask
from taskiq.scheduler.scheduled_task import CronSpec

from src.config.settings import PapilioSettings
from src.modules.operations.automation.domain.dtos import (
    ScheduleKey,
    SchedulePolicy,
)


class RuntimeScheduleStore:
    def __init__(self, source: RedisSource, settings: PapilioSettings) -> None:
        self.source = source
        self.prefix = settings.operations.automation_registration_prefix

    async def reconcile(
        self,
        key: ScheduleKey,
        task: AsyncTaskiqDecoratedTask,
        policy: SchedulePolicy,
        revision: int,
    ) -> None:
        identifier = self.prefix + key.value
        inventory = await self.source.list_schedules()
        previous = next(
            (item for item in inventory if item.schedule_id == identifier),
            None,
        )
        if not policy.enabled:
            await self.source.delete_schedule(identifier)
            return
        if (
            previous is not None
            and previous.task_name == task.task_name
            and previous.interval == policy.interval_seconds
            and previous.cron == policy.cron
            and previous.cron_offset == policy.timezone
            and previous.args == []
            and previous.kwargs == {"expected_revision": revision}
            and str(previous.labels.get("retry_on_error", "")).lower()
            == "true"
        ):
            return
        await self.source.delete_schedule(identifier)
        if policy.interval_seconds is not None:
            await (
                task.kicker()
                .with_schedule_id(identifier)
                .schedule_by_interval(
                    self.source.native,
                    policy.interval_seconds,
                    expected_revision=revision,
                )
            )
        else:
            assert policy.cron is not None and policy.timezone is not None
            minute, hour, day, month, weekday = policy.cron.split()
            expression = CronSpec(
                minutes=minute,
                hours=hour,
                days=day,
                months=month,
                weekdays=weekday,
                offset=policy.timezone,
            )
            await (
                task.kicker()
                .with_schedule_id(identifier)
                .schedule_by_cron(
                    self.source.native, expression, expected_revision=revision
                )
            )
