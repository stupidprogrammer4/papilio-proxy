import asyncio

from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler
from papilio_tasks.tools.retry import Retry
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import PapilioSettings
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.operations.notifications.interfaces import (
    INotificationDeliveryHandler,
    INotificationQuery,
)

policy = get_settings(PapilioSettings).operations


class DeliverNotification(RedisScheduler):
    retry = Retry(
        attempts=policy.automation_retry_attempts,
        delay=policy.automation_retry_delay_seconds,
        errors=(SQLAlchemyError,),
    )

    def __init__(self, handler: INotificationDeliveryHandler) -> None:
        self.handler = handler

    async def run(self, notification_id: int) -> bool:
        result = await self.handler.deliver(notification_id)
        return result


class ScanNotifications(RedisScheduler):
    retry = Retry(
        attempts=policy.automation_retry_attempts,
        delay=policy.automation_retry_delay_seconds,
        errors=(SQLAlchemyError, RedisError, ExceptionGroup),
    )

    def __init__(
        self, query: INotificationQuery, policies: IAutomationPolicyQuery
    ) -> None:
        self.query, self.policies = query, policies

    async def run(self, expected_revision: int | None = None) -> int:
        current = await self.policies.schedule(ScheduleKey.NOTIFICATIONS)
        if (
            not current.runnable
            or expected_revision is not None
            and expected_revision != current.revision
        ):
            return 0
        ids = await self.query.due_ids()
        outcomes = await asyncio.gather(
            *(DeliverNotification.enqueue(notification_id=id) for id in ids),
            return_exceptions=True,
        )
        failures = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, BaseException)
        ]
        if failures:
            raise BaseExceptionGroup(
                "Notification scheduling failed", failures
            )
        return len(ids)
