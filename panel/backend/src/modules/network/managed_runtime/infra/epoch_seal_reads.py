"""Read bounded epoch evidence for application-owned closure decisions."""

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.managed_runtime.domain.epoch_seals import (
    ManagedEpochSealBarrierFacts,
    ManagedEpochSealEpochHint,
    ManagedEpochSealGrantFacts,
    ManagedEpochSealRead,
)
from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorWindowFacts,
)
from src.modules.network.managed_runtime.infra.tables import (
    ManagedBarrierTable,
    ManagedEpochTable,
    ManagedWindowTable,
)
from src.modules.network.usage.infra.tables import UsageGrantTable


class ManagedEpochSealReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def epoch_hint(self, epoch: str) -> ManagedEpochSealEpochHint | None:
        result = await self.uow.execute(
            select(ManagedEpochTable).where(
                col(ManagedEpochTable.process_epoch) == epoch
            )
        )
        row = result.scalar_one_or_none()
        return (
            ManagedEpochSealEpochHint.model_validate(row.model_dump())
            if row is not None
            else None
        )

    async def locked_epoch(
        self, epoch_id: int, process_epoch: str, node_id: int, limit: int
    ) -> ManagedEpochSealRead:
        windows = await self.uow.execute(
            select(ManagedWindowTable)
            .where(col(ManagedWindowTable.epoch_id) == epoch_id)
            .order_by(col(ManagedWindowTable.id))
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        grants = await self.uow.execute(
            select(UsageGrantTable)
            .where(
                col(UsageGrantTable.process_epoch) == process_epoch,
                col(UsageGrantTable.node_id) == node_id,
            )
            .order_by(col(UsageGrantTable.id))
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        barriers = await self.uow.execute(
            select(ManagedBarrierTable)
            .where(col(ManagedBarrierTable.epoch_id) == epoch_id)
            .order_by(col(ManagedBarrierTable.id))
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return ManagedEpochSealRead(
            windows=tuple(
                ManagedSuccessorWindowFacts.model_validate(row.model_dump())
                for row in windows.scalars()
            ),
            grants=tuple(
                ManagedEpochSealGrantFacts.model_validate(row.model_dump())
                for row in grants.scalars()
            ),
            barriers=tuple(
                ManagedEpochSealBarrierFacts.model_validate(row.model_dump())
                for row in barriers.scalars()
            ),
        )
