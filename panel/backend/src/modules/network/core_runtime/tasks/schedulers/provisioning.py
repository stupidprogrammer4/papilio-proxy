import asyncio

from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler
from papilio_tasks.tools.retry import Retry
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.interfaces import (
    ICoreProvisioningCommand,
    ICoreProvisioningQuery,
)
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery

settings = get_settings(PapilioSettings)


class EnsureCoreProvisioning(RedisScheduler):
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(SQLAlchemyError,),
    )

    def __init__(self, command: ICoreProvisioningCommand) -> None:
        self.command = command

    async def run(self, core_id: int) -> str:
        result = await self.command.ensure(core_id)
        return result.state


class ScanCoreProvisioning(RedisScheduler):
    retry = Retry(
        attempts=settings.operations.automation_retry_attempts,
        delay=settings.operations.automation_retry_delay_seconds,
        errors=(SQLAlchemyError, RedisError, ExceptionGroup),
    )

    def __init__(
        self, query: ICoreProvisioningQuery, policies: IAutomationPolicyQuery
    ) -> None:
        self.query, self.policies = query, policies

    async def run(self, expected_revision: int | None = None) -> int:
        current = await self.policies.schedule(ScheduleKey.CORE_PROVISIONING)
        if not current.runnable or (
            expected_revision is not None
            and expected_revision != current.revision
        ):
            return 0
        ids = await self.query.due_core_ids(current.values.batch_size)
        outcomes = await asyncio.gather(
            *(EnsureCoreProvisioning.enqueue(core_id=id) for id in ids),
            return_exceptions=True,
        )
        failures = [
            result for result in outcomes if isinstance(result, BaseException)
        ]
        if failures:
            raise BaseExceptionGroup(
                "Core provisioning scheduling failed", failures
            )
        return len(ids)
