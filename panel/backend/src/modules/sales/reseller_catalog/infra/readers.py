from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.sales.catalog.infra.tables import PlanTable
from src.modules.sales.reseller_catalog.domain.results import ResellerPlanFacts
from src.modules.sales.reseller_catalog.infra.tables import ResellerPlanTable


class ResellerPlanReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def for_plan(
        self, reseller_id: int, plan_id: int, lock: bool = False
    ) -> ResellerPlanFacts | None:
        query = (
            select(ResellerPlanTable, PlanTable)
            .join(
                PlanTable, col(PlanTable.id) == col(ResellerPlanTable.plan_id)
            )
            .where(
                col(ResellerPlanTable.reseller_id) == reseller_id,
                col(ResellerPlanTable.plan_id) == plan_id,
            )
        )
        if lock:
            query = query.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(query)
        row = result.one_or_none()
        return (
            None
            if row is None
            else ResellerPlanFacts(row.ResellerPlanTable, row.PlanTable)
        )

    async def owned(
        self, reseller_id: int, id: int
    ) -> ResellerPlanFacts | None:
        result = await self.uow.execute(
            select(ResellerPlanTable, PlanTable)
            .join(
                PlanTable, col(PlanTable.id) == col(ResellerPlanTable.plan_id)
            )
            .where(
                col(ResellerPlanTable.reseller_id) == reseller_id,
                col(ResellerPlanTable.id) == id,
            )
        )
        row = result.one_or_none()
        return (
            None
            if row is None
            else ResellerPlanFacts(row.ResellerPlanTable, row.PlanTable)
        )

    async def page(
        self,
        reseller_id: int,
        q: str | None,
        agreement_enabled: bool | None,
        plan_active: bool | None,
        offset: int,
        limit: int,
    ) -> PagedType[ResellerPlanFacts]:
        query = (
            select(ResellerPlanTable, PlanTable)
            .join(
                PlanTable, col(PlanTable.id) == col(ResellerPlanTable.plan_id)
            )
            .where(col(ResellerPlanTable.reseller_id) == reseller_id)
        )
        if q:
            query = query.where(
                col(PlanTable.title).like(f"%{q}%")
                | col(PlanTable.code).like(f"%{q}%")
            )
        if agreement_enabled is not None:
            query = query.where(
                col(ResellerPlanTable.enabled) == agreement_enabled
            )
        if plan_active is not None:
            query = query.where(col(PlanTable.is_active) == plan_active)
        count = await self.uow.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count.scalar_one()
        result = await self.uow.execute(
            query.order_by(
                col(PlanTable.sort_order), col(ResellerPlanTable.id)
            )
            .offset(offset)
            .limit(limit)
        )
        return PagedType(
            [
                ResellerPlanFacts(row.ResellerPlanTable, row.PlanTable)
                for row in result.all()
            ],
            total,
        )
