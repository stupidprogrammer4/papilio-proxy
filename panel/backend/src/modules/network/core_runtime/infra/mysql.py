from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeCommandModel,
    CoreRuntimeRevisionModel,
    CoreRuntimeStateModel,
)
from src.modules.network.core_runtime.infra.tables import (
    CoreRuntimeCommandTable,
    CoreRuntimeRevisionTable,
    CoreRuntimeStateTable,
)
from src.modules.network.cores.infra.tables import CoreTable
from src.modules.network.nodes.infra.tables import NodeTable


class RuntimeStateRepository(
    MySQLPersistenceRepository[CoreRuntimeStateModel]
):
    table = CoreRuntimeStateTable

    async def lock_node_for_core(self, core_id: int) -> None:
        result = await self.uow.execute(
            select(col(NodeTable.id))
            .where(
                col(NodeTable.id).in_(
                    select(col(CoreTable.node_id)).where(
                        col(CoreTable.id) == core_id
                    )
                )
            )
            .with_for_update()
        )
        result.scalar_one()

    async def lock_nodes_for_cores(self, core_ids: list[int]) -> None:
        result = await self.uow.execute(
            select(col(NodeTable.id))
            .where(
                col(NodeTable.id).in_(
                    select(col(CoreTable.node_id)).where(
                        col(CoreTable.id).in_(core_ids)
                    )
                )
            )
            .order_by(col(NodeTable.id))
            .with_for_update()
        )
        result.scalars().all()

    async def lock_core(self, core_id: int) -> None:
        result = await self.uow.execute(
            select(CoreTable)
            .where(col(CoreTable.id) == core_id)
            .with_for_update()
        )
        result.scalar_one()

    async def lock_cores(self, core_ids: list[int]) -> None:
        if not core_ids:
            return
        result = await self.uow.execute(
            select(CoreTable)
            .where(col(CoreTable.id).in_(core_ids))
            .order_by(col(CoreTable.id))
            .with_for_update()
        )
        result.scalars().all()

    async def for_core(
        self, core_id: int, lock: bool = False
    ) -> CoreRuntimeStateModel | None:
        query = (
            select(CoreRuntimeStateTable)
            .where(col(CoreRuntimeStateTable.core_id) == core_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        result = await self.uow.execute(query)
        return result.scalar_one_or_none()

    async def change(
        self, row: CoreRuntimeStateModel, patch: CoreRuntimeStateModel
    ) -> CoreRuntimeStateModel:
        await self.update_row_by_id(row.id, patch)
        result = await self.for_core(row.core_id, lock=True)
        assert result is not None
        return result


class RuntimeRevisionRepository(
    MySQLPersistenceRepository[CoreRuntimeRevisionModel]
):
    table = CoreRuntimeRevisionTable

    async def current(
        self, id: int, core_id: int
    ) -> CoreRuntimeRevisionModel | None:
        result = await self.uow.execute(
            select(CoreRuntimeRevisionTable)
            .where(
                col(CoreRuntimeRevisionTable.id) == id,
                col(CoreRuntimeRevisionTable.core_id) == core_id,
            )
            .with_for_update(read=True)
        )
        return result.scalar_one_or_none()


class RuntimeCommandRepository(
    MySQLPersistenceRepository[CoreRuntimeCommandModel]
):
    table = CoreRuntimeCommandTable

    async def by_key(
        self, core_id: int, request_key: str
    ) -> CoreRuntimeCommandModel | None:
        result = await self.uow.execute(
            select(CoreRuntimeCommandTable)
            .where(
                col(CoreRuntimeCommandTable.core_id) == core_id,
                col(CoreRuntimeCommandTable.request_key) == request_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def outstanding(
        self, core_id: int, states: list[str]
    ) -> CoreRuntimeCommandModel | None:
        result = await self.uow.execute(
            select(CoreRuntimeCommandTable)
            .where(
                col(CoreRuntimeCommandTable.core_id) == core_id,
                col(CoreRuntimeCommandTable.state).in_(states),
            )
            .with_for_update()
        )
        return result.scalars().first()

    async def page(
        self, core_id: int | None, node_id: int | None, offset: int, limit: int
    ) -> PagedType[CoreRuntimeCommandModel]:
        query = select(CoreRuntimeCommandTable).order_by(
            col(CoreRuntimeCommandTable.id).desc()
        )
        if core_id is not None:
            query = query.where(
                col(CoreRuntimeCommandTable.core_id) == core_id
            )
        if node_id is not None:
            query = query.where(
                col(CoreRuntimeCommandTable.node_id) == node_id
            )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result

    async def actionable_page(
        self,
        node_id: int,
        states: list[str],
        before: datetime,
        offset: int,
        limit: int,
    ) -> PagedType[CoreRuntimeCommandModel]:
        query = (
            select(CoreRuntimeCommandTable)
            .where(
                col(CoreRuntimeCommandTable.node_id) == node_id,
                col(CoreRuntimeCommandTable.state).in_(states),
                col(CoreRuntimeCommandTable.available_at) <= before,
                (
                    col(CoreRuntimeCommandTable.claim_until).is_(None)
                    | (col(CoreRuntimeCommandTable.claim_until) <= before)
                ),
            )
            .order_by(col(CoreRuntimeCommandTable.id))
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result

    async def current(
        self, id: int, lock: bool = False
    ) -> CoreRuntimeCommandModel | None:
        query = (
            select(CoreRuntimeCommandTable)
            .where(col(CoreRuntimeCommandTable.id) == id)
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        result = await self.uow.execute(query)
        return result.scalar_one_or_none()

    async def change(
        self, row: CoreRuntimeCommandModel, patch: CoreRuntimeCommandModel
    ) -> CoreRuntimeCommandModel:
        await self.update_row_by_id(row.id, patch)
        result = await self.current(row.id, lock=True)
        assert result is not None
        return result
