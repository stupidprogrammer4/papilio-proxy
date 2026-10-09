import asyncio

from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler
from papilio_tasks.tools.retry import Retry
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.interfaces import (
    ICoreRuntimeCommand,
    ICoreRuntimeQuery,
)
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery

settings = get_settings(PapilioSettings)


class RecoverCoreRuntime(RedisScheduler):
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(SQLAlchemyError,),
    )

    def __init__(self, command: ICoreRuntimeCommand) -> None:
        self.command = command

    async def run(self, command_id: int) -> str:
        result = await self.command.recover(command_id)
        return result.state


class ScanCoreRuntime(RedisScheduler):
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(SQLAlchemyError, RedisError, ExceptionGroup),
    )

    def __init__(
        self, query: ICoreRuntimeQuery, policies: IAutomationPolicyQuery
    ) -> None:
        self.query = query
        self.policies = policies

    async def run(self, expected_revision: int | None = None) -> int:
        current = await self.policies.schedule(ScheduleKey.CORE_RUNTIME)
        if not current.runnable or (
            expected_revision is not None
            and expected_revision != current.revision
        ):
            return 0
        ids = await self.query.due_command_ids(current.values.batch_size)
        outcomes = await asyncio.gather(
            *(RecoverCoreRuntime.enqueue(command_id=id) for id in ids),
            return_exceptions=True,
        )
        failures = [
            item for item in outcomes if isinstance(item, BaseException)
        ]
        if failures:
            raise BaseExceptionGroup(
                "Core runtime recovery scheduling failed", failures
            )
        return len(ids)
