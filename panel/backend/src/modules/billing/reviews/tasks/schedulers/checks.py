import asyncio

from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler
from papilio_tasks.tools.retry import Retry
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import PapilioSettings
from src.modules.billing.reviews.interfaces import (
    IPaymentReviewCommand,
    IPaymentReviewQuery,
)
from src.modules.billing.sms_devices.interfaces import ISmsSettlementCommand
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.sales.checkout.interfaces import ICheckoutFundingPublisher

policy = get_settings(PapilioSettings).operations


class CheckPaymentReview(RedisScheduler):
    retry = Retry(
        attempts=policy.automation_retry_attempts,
        delay=policy.automation_retry_delay_seconds,
        errors=(SQLAlchemyError,),
    )

    def __init__(
        self,
        command: IPaymentReviewCommand,
        settlement: ISmsSettlementCommand,
        checkout_publisher: ICheckoutFundingPublisher,
    ) -> None:
        self.checkout_publisher = checkout_publisher
        self.command = command
        self.settlement = settlement

    async def run(self, topup_id: int) -> str:
        result = await self.command.check(topup_id)
        status = await self.settlement.check_topup(topup_id)
        await self.checkout_publisher.publish(topup_id)
        return status if status == "approved" else result.status


class ScanPaymentReview(RedisScheduler):
    retry = Retry(
        attempts=policy.automation_retry_attempts,
        delay=policy.automation_retry_delay_seconds,
        errors=(SQLAlchemyError, RedisError, ExceptionGroup),
    )

    def __init__(
        self,
        query: IPaymentReviewQuery,
        policies: IAutomationPolicyQuery,
    ) -> None:
        self.query = query
        self.policies = policies

    async def run(self, expected_revision: int | None = None) -> int:
        current = await self.policies.schedule(ScheduleKey.PAYMENTS)
        if not current.runnable or (
            expected_revision is not None
            and expected_revision != current.revision
        ):
            return 0
        ids = await self.query.due_ids()
        outcomes = await asyncio.gather(
            *(CheckPaymentReview.enqueue(topup_id=id) for id in ids),
            return_exceptions=True,
        )
        failures = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, BaseException)
        ]
        if failures:
            raise BaseExceptionGroup("Check scheduling failed", failures)
        return len(ids)
