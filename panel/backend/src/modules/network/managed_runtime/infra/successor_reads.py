"""Ordered epoch facts; application owns capacity and chain decisions."""

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorChainRead,
    ManagedSuccessorWindowFacts,
)
from src.modules.network.managed_runtime.infra.tables import ManagedWindowTable


class ManagedSuccessorReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def initial_hint(
        self, profile_id: int, epoch_id: int
    ) -> ManagedSuccessorWindowFacts | None:
        result = await self.uow.execute(
            select(ManagedWindowTable).where(
                col(ManagedWindowTable.profile_id) == profile_id,
                col(ManagedWindowTable.epoch_id) == epoch_id,
                col(ManagedWindowTable.predecessor_id).is_(None),
            )
        )
        row = result.scalar_one_or_none()
        return (
            ManagedSuccessorWindowFacts.model_validate(row.model_dump())
            if row is not None
            else None
        )

    async def locked_epoch(
        self, epoch_id: int, limit: int
    ) -> ManagedSuccessorChainRead:
        result = await self.uow.execute(
            select(ManagedWindowTable)
            .where(col(ManagedWindowTable.epoch_id) == epoch_id)
            .order_by(col(ManagedWindowTable.id))
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return ManagedSuccessorChainRead(
            windows=tuple(
                ManagedSuccessorWindowFacts.model_validate(row.model_dump())
                for row in result.scalars()
            )
        )
