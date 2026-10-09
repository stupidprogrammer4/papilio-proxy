import asyncio

from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler
from papilio_tasks.tools.retry import Retry
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import PapilioSettings
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.sales.subscriptions.interfaces import (
    ICustomerHoldCommand,
    ICustomerHoldFinalizeCommand,
    ICustomerHoldFinalizeQuery,
    ICustomerHoldQuery,
)

settings = get_settings(PapilioSettings)


class CheckCustomerHold(RedisScheduler):
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(SQLAlchemyError,),
    )

    def __init__(self, command: ICustomerHoldCommand) -> None:
        self.command = command

    async def run(self, subscription_id: int) -> str:
        result = await self.command.check(subscription_id)
        return result.status


class FinalizeCustomerHold(RedisScheduler):
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(SQLAlchemyError,),
    )

    def __init__(self, command: ICustomerHoldFinalizeCommand) -> None:
        self.command = command

    async def run(self, customer_id: int) -> bool:
        result = await self.command.check(customer_id)
        return result


class ScanCustomerHolds(RedisScheduler):
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(SQLAlchemyError, RedisError, ExceptionGroup),
    )

    def __init__(
        self,
        query: ICustomerHoldQuery,
        finalization: ICustomerHoldFinalizeQuery,
        policies: IAutomationPolicyQuery,
    ) -> None:
        self.query = query
        self.policies = policies
        self.finalization = finalization

    async def run(self, expected_revision: int | None = None) -> int:
        current = await self.policies.schedule(ScheduleKey.CUSTOMER_HOLDS)
        if not current.runnable or (
            expected_revision is not None
            and expected_revision != current.revision
        ):
            return 0
        ids = await self.query.due_ids()
        customer_ids = await self.finalization.due_ids()
        outcomes = await asyncio.gather(
            *(CheckCustomerHold.enqueue(subscription_id=id) for id in ids),
            *(
                FinalizeCustomerHold.enqueue(customer_id=id)
                for id in customer_ids
            ),
            return_exceptions=True,
        )
        failures = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, BaseException)
        ]
        if failures:
            raise BaseExceptionGroup(
                "Customer hold scheduling failed", failures
            )
        return len(ids) + len(customer_ids)
