import asyncio

from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler
from papilio_tasks.tools.retry import Retry
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import PapilioSettings
from src.modules.billing.reviews.tasks.schedulers.checks import (
    ScanPaymentReview,
)
from src.modules.network.core_runtime.tasks.schedulers.provisioning import (
    ScanCoreProvisioning,
)
from src.modules.network.core_runtime.tasks.schedulers.recovery import (
    ScanCoreRuntime,
)
from src.modules.network.health.tasks.schedulers.checks import ScanNodeHealth
from src.modules.network.provisioning.tasks.schedulers.checks import (
    ScanProvisioning,
)
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import (
    IAutomationRegistrationCommand,
)
from src.modules.operations.notifications.tasks.schedulers.delivery import (
    ScanNotifications,
)
from src.modules.sales.attention.tasks.schedulers.checks import (
    ScanSubscriptionAttention,
)
from src.modules.sales.checkout.tasks.schedulers.recovery import ScanCheckouts
from src.modules.sales.subscriptions.tasks.schedulers.customer_holds import (
    ScanCustomerHolds,
)
from src.modules.sales.subscriptions.tasks.schedulers.lifecycle import (
    ScanSubscriptionLifecycle,
)
from src.modules.sales.subscriptions.tasks.schedulers.renewals import (
    ScanRenewals,
)

settings = get_settings(PapilioSettings)

SCHEDULE_TASKS: dict[ScheduleKey, type[RedisScheduler]] = {
    ScheduleKey.CHECKOUT: ScanCheckouts,
    ScheduleKey.NOTIFICATIONS: ScanNotifications,
    ScheduleKey.CORE_RUNTIME: ScanCoreRuntime,
    ScheduleKey.CORE_PROVISIONING: ScanCoreProvisioning,
    ScheduleKey.CUSTOMER_HOLDS: ScanCustomerHolds,
    ScheduleKey.LIFECYCLE: ScanSubscriptionLifecycle,
    ScheduleKey.PROVISIONING: ScanProvisioning,
    ScheduleKey.PAYMENTS: ScanPaymentReview,
    ScheduleKey.NODES: ScanNodeHealth,
    ScheduleKey.ATTENTION: ScanSubscriptionAttention,
    ScheduleKey.RENEWALS: ScanRenewals,
}


class ReconcileAutomationSchedule(RedisScheduler):
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(SQLAlchemyError, RedisError),
    )

    def __init__(self, command: IAutomationRegistrationCommand) -> None:
        self.command = command

    async def run(self, key: str) -> int:
        selected = ScheduleKey(key)
        task = SCHEDULE_TASKS[selected].task()
        result = await self.command.reconcile(selected, task)
        return result


class ScanAutomationRegistrations(RedisScheduler):
    schedule = [{"cron": settings.operations.automation_registration_cron}]
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(RedisError, ExceptionGroup),
    )

    async def run(self) -> int:
        outcomes = await asyncio.gather(
            *(
                ReconcileAutomationSchedule.enqueue(key=key.value)
                for key in ScheduleKey
            ),
            return_exceptions=True,
        )
        failures = [
            item for item in outcomes if isinstance(item, BaseException)
        ]
        if failures:
            raise BaseExceptionGroup(
                "Automation registration scheduling failed", failures
            )
        return len(outcomes)
