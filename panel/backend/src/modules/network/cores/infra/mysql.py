from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import or_, select
from sqlmodel import col

from src.modules.network.cores.domain.models import CoreModel
from src.modules.network.cores.infra.tables import CoreTable


class CoreRepository(MySQLPersistenceRepository[CoreModel]):
    table = CoreTable

    async def reserve_default(self, data: CoreModel) -> CoreModel:
        await self.upsert(data, update_columns=[CoreTable.__table__.c.code])
        rows = await self.uow.execute(
            select(CoreTable)
            .where(
                col(CoreTable.node_id) == data.node_id,
                col(CoreTable.code) == data.code,
            )
            .with_for_update()
        )
        return rows.scalar_one()

    async def by_code(self, node_id: int, code: str) -> CoreModel | None:
        result = await self.uow.execute(
            select(CoreTable).where(
                col(CoreTable.node_id) == node_id, col(CoreTable.code) == code
            )
        )
        return result.scalar_one_or_none()

    async def page(
        self, node_id: int, q: str | None, offset: int, limit: int
    ) -> PagedType[CoreModel]:
        query = (
            select(CoreTable)
            .where(col(CoreTable.node_id) == node_id)
            .order_by(col(CoreTable.id).desc())
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
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
