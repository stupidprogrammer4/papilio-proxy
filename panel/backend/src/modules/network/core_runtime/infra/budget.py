from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import or_, select
from sqlmodel import col

from src.modules.network.core_runtime.domain.memberships import (
    RuntimeProvisioningAttempt,
)
from src.modules.network.core_runtime.infra.tables import (
    CoreRuntimeCommandTable as Task,
)


class RuntimeProvisioningBudgetReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def latest_success(
        self,
        core_id: int,
        revision_id: int,
        actions: list[str],
        restore_action: str,
        restore_mode: str,
        states: list[str],
        limit: int,
    ) -> int:
        result = await self.uow.execute(
            select(col(Task.id))
            .where(
                col(Task.core_id) == core_id,
                col(Task.revision_id) == revision_id,
                or_(
                    col(Task.action).in_(actions),
                    (col(Task.action) == restore_action)
                    & (col(Task.reconcile_mode) == restore_mode),
                ),
                col(Task.state).in_(states),
            )
            .order_by(col(Task.id).desc())
            .limit(limit)
            .with_for_update(read=True)
        )
        return result.scalar_one_or_none() or 0

    async def attempts(
        self,
        core_id: int,
        revision_id: int,
        purpose: str,
        actions: list[str],
        restore_action: str,
        restore_mode: str,
        after_id: int,
        minimum_attempts: int,
        limit: int,
    ) -> list[RuntimeProvisioningAttempt]:
        result = await self.uow.execute(
            select(col(Task.attempts), col(Task.updated_at))
            .where(
                col(Task.core_id) == core_id,
                col(Task.revision_id) == revision_id,
                col(Task.purpose) == purpose,
                or_(
                    col(Task.action).in_(actions),
                    (col(Task.action) == restore_action)
                    & (col(Task.reconcile_mode) == restore_mode),
                ),
                col(Task.id) > after_id,
                col(Task.attempts) >= minimum_attempts,
            )
            .order_by(col(Task.id).desc())
            .limit(limit)
            .with_for_update(read=True)
        )
        return [
            RuntimeProvisioningAttempt.model_validate(row._mapping)
            for row in result
        ]
