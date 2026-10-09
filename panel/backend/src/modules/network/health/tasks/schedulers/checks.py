import asyncio

from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler
from papilio_tasks.tools.retry import Retry
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import PapilioSettings
from src.modules.network.health.interfaces import (
    INodeHealthCommand,
    INodeHealthQuery,
)
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery

policy = get_settings(PapilioSettings).operations


class CheckNodeHealth(RedisScheduler):
    retry = Retry(
        attempts=policy.automation_retry_attempts,
        delay=policy.automation_retry_delay_seconds,
        errors=(SQLAlchemyError,),
    )

    def __init__(self, command: INodeHealthCommand) -> None:
        self.command = command

    async def run(self, node_id: int) -> str:
        result = await self.command.check(node_id)
        return result.status


class ScanNodeHealth(RedisScheduler):
    retry = Retry(
        attempts=policy.automation_retry_attempts,
        delay=policy.automation_retry_delay_seconds,
        errors=(SQLAlchemyError, RedisError, ExceptionGroup),
    )

    def __init__(
        self,
        query: INodeHealthQuery,
        policies: IAutomationPolicyQuery,
    ) -> None:
        self.query = query
        self.policies = policies

    async def run(self, expected_revision: int | None = None) -> int:
        current = await self.policies.schedule(ScheduleKey.NODES)
        if not current.runnable or (
            expected_revision is not None
            and expected_revision != current.revision
        ):
            return 0
        ids = await self.query.due_ids()
        outcomes = await asyncio.gather(
            *(CheckNodeHealth.enqueue(node_id=id) for id in ids),
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
