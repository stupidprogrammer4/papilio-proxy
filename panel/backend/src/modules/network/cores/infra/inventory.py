from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, or_, select
from sqlmodel import col

from src.modules.network.core_runtime.infra.tables import CoreRuntimeStateTable
from src.modules.network.cores.domain.results import CoreInventoryFacts
from src.modules.network.cores.infra.tables import CoreTable


class CoreInventoryReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def detail(self, core_id: int) -> CoreInventoryFacts | None:
        result = await self.uow.execute(
            select(CoreTable, CoreRuntimeStateTable)
            .outerjoin(
                CoreRuntimeStateTable,
                col(CoreRuntimeStateTable.core_id) == col(CoreTable.id),
            )
            .where(col(CoreTable.id) == core_id)
        )
        row = result.one_or_none()
        return (
            None
            if row is None
            else CoreInventoryFacts(row.CoreTable, row.CoreRuntimeStateTable)
        )

    async def page(
        self, node_id: int, q: str | None, offset: int, limit: int
    ) -> PagedType[CoreInventoryFacts]:
        query = (
            select(CoreTable, CoreRuntimeStateTable)
            .outerjoin(
                CoreRuntimeStateTable,
                col(CoreRuntimeStateTable.core_id) == col(CoreTable.id),
            )
            .where(col(CoreTable.node_id) == node_id)
        )
        if q:
            pattern = (
                "%"
                + q.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                + "%"
            )
            query = query.where(
                or_(
                    col(CoreTable.label).like(pattern),
                    col(CoreTable.code).like(pattern),
                )
            )
        total = await self.uow.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        rows = await self.uow.execute(
            query.order_by(col(CoreTable.id).desc())
            .limit(limit)
            .offset(offset)
        )
        return PagedType(
            [
                CoreInventoryFacts(row.CoreTable, row.CoreRuntimeStateTable)
                for row in rows
            ],
            total.scalar_one(),
        )
