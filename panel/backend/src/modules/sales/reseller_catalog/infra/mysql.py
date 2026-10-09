from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.sales.reseller_catalog.domain.models import (
    ResellerPlanChangeModel,
    ResellerPlanModel,
)
from src.modules.sales.reseller_catalog.infra.tables import (
    ResellerPlanChangeTable,
    ResellerPlanTable,
)


class ResellerPlanRepository(MySQLPersistenceRepository[ResellerPlanModel]):
    table = ResellerPlanTable

    async def owned(
        self, reseller_id: int, id: int, lock: bool = False
    ) -> ResellerPlanModel | None:
        query = select(self.table).where(
            col(self.table.reseller_id) == reseller_id,
            col(self.table.id) == id,
        )
        if lock:
            query = query.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(query)
        return result.scalar_one_or_none()

    async def count_locked(self, reseller_id: int) -> int:
        result = await self.uow.execute(
            select(func.count())
            .select_from(self.table)
            .where(col(self.table.reseller_id) == reseller_id)
            .with_for_update()
        )
        return result.scalar_one()


class ResellerPlanChangeRepository(
    MySQLPersistenceRepository[ResellerPlanChangeModel]
):
    table = ResellerPlanChangeTable

    async def page(
        self, agreement_id: int, offset: int, limit: int
    ) -> PagedType[ResellerPlanChangeModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.agreement_id) == agreement_id)
            .order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result
