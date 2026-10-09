from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.catalog.infra.tables import PlanTable


class PlanRepository(MySQLPersistenceRepository[PlanModel]):
    table = PlanTable

    async def locked(self, id: int) -> PlanModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def update_existing(
        self, existing: PlanModel, changes: PlanModel
    ) -> PlanModel:
        await self.update_row_by_id(existing.id, changes)
        await self.uow.refresh(existing)
        return existing

    async def get_by_code(self, code: str) -> PlanModel | None:
        result = await self.uow.execute(
            select(PlanTable).where(col(PlanTable.code) == code)
        )
        return result.scalar_one_or_none()

    async def search_page(
        self, *, q: str | None, active: bool | None, offset: int, limit: int
    ) -> PagedType[PlanModel]:
        query = select(PlanTable)
        if q:
            query = query.where(
                func.lower(col(PlanTable.title)).like(f"%{q.lower()}%")
            )
        if active is not None:
            query = query.where(col(PlanTable.is_active).is_(active))
        query = query.order_by(
            col(PlanTable.sort_order), col(PlanTable.id).desc()
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
