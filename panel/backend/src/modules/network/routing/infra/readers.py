from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.network.routing.domain.results import GroupHostFacts
from src.modules.network.routing.infra.tables import (
    HostGroupTable,
    HostMembershipTable,
    HostTable,
)


class GroupHostReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def page(
        self, group_id: int, q: str | None, offset: int, limit: int
    ) -> PagedType[GroupHostFacts]:
        query = (
            select(HostTable, HostGroupTable, HostMembershipTable)
            .join(
                HostMembershipTable,
                col(HostMembershipTable.host_id) == col(HostTable.id),
            )
            .join(
                HostGroupTable,
                col(HostGroupTable.id) == col(HostMembershipTable.group_id),
            )
            .where(col(HostGroupTable.id) == group_id)
            .order_by(
                col(HostMembershipTable.sort_order),
                col(HostMembershipTable.id),
            )
        )
        if q:
            pattern = (
                "%"
                + q.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                + "%"
            )
            query = query.where(col(HostTable.label).like(pattern))
        counted = await self.uow.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        rows = await self.uow.execute(query.offset(offset).limit(limit))
        return PagedType(
            items=[
                GroupHostFacts(
                    row.HostTable, row.HostGroupTable, row.HostMembershipTable
                )
                for row in rows
            ],
            total_items=counted.scalar_one(),
        )
