import asyncio

from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler
from papilio_tasks.tools.retry import Retry
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import PapilioSettings
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.sales.checkout.interfaces import (
    ICheckoutRecoveryQuery,
    ICheckoutRecoveryRunner,
)

settings = get_settings(PapilioSettings).operations


class RecoverCheckout(RedisScheduler):
    retry = Retry(
        attempts=settings.automation_retry_attempts,
        delay=settings.automation_retry_delay_seconds,
        errors=(SQLAlchemyError,),
    )

    def __init__(self, runner: ICheckoutRecoveryRunner) -> None:
        self.runner = runner

    async def run(self, checkout_id: int) -> int:
        result = await self.runner.run(checkout_id)
        return result.id


class ScanCheckouts(RedisScheduler):
    retry = Retry(
        attempts=settings.automation_retry_attempts,
        delay=settings.automation_retry_delay_seconds,
        errors=(SQLAlchemyError, RedisError, ExceptionGroup),
    )

    def __init__(
        self, query: ICheckoutRecoveryQuery, policies: IAutomationPolicyQuery
    ) -> None:
        self.query, self.policies = query, policies

    async def run(self, expected_revision: int | None = None) -> int:
        current = await self.policies.schedule(ScheduleKey.CHECKOUT)
        if (
            not current.runnable
            or expected_revision is not None
            and current.revision != expected_revision
        ):
            return 0
        ids = await self.query.due_ids(
            current.values.batch_size, current.values.recheck_seconds
        )
        outcomes = await asyncio.gather(
            *(RecoverCheckout.enqueue(checkout_id=id) for id in ids),
            return_exceptions=True,
        )
        failures = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, BaseException)
        ]
        if failures:
            raise BaseExceptionGroup(
                "Checkout recovery scheduling failed", failures
            )
        return len(ids)
