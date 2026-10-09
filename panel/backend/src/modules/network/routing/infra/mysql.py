from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.routing.domain.models import (
    HostGroupModel,
    HostMembershipModel,
    HostModel,
)
from src.modules.network.routing.infra.tables import (
    HostGroupTable,
    HostMembershipTable,
    HostTable,
)


class HostRepository(MySQLPersistenceRepository[HostModel]):
    table = HostTable

    async def page(
        self,
        configuration_id: int | None,
        q: str | None,
        offset: int,
        limit: int,
    ) -> PagedType[HostModel]:
        query = select(HostTable).order_by(col(HostTable.id).desc())
        if configuration_id is not None:
            query = query.where(
                col(HostTable.configuration_id) == configuration_id
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
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result

    async def change(
        self, existing: HostModel, changes: HostModel
    ) -> HostModel:
        await self.update_row_by_id(existing.id, changes)
        await self.uow.refresh(existing)
        return existing


class HostGroupRepository(MySQLPersistenceRepository[HostGroupModel]):
    table = HostGroupTable

    async def page(
        self, q: str | None, offset: int, limit: int
    ) -> PagedType[HostGroupModel]:
        query = select(HostGroupTable).order_by(col(HostGroupTable.id).desc())
        if q:
            pattern = (
                "%"
                + q.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                + "%"
            )
            query = query.where(col(HostGroupTable.title).like(pattern))
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result

    async def change(
        self, existing: HostGroupModel, changes: HostGroupModel
    ) -> HostGroupModel:
        await self.update_row_by_id(existing.id, changes)
        await self.uow.refresh(existing)
        return existing


class HostMembershipRepository(
    MySQLPersistenceRepository[HostMembershipModel]
):
    table = HostMembershipTable

    async def find(
        self, group_id: int, host_id: int
    ) -> HostMembershipModel | None:
        result = await self.uow.execute(
            select(HostMembershipTable).where(
                col(HostMembershipTable.group_id) == group_id,
                col(HostMembershipTable.host_id) == host_id,
            )
        )
        return result.scalar_one_or_none()

    async def change(
        self, existing: HostMembershipModel, changes: HostMembershipModel
    ) -> HostMembershipModel:
        await self.update_row_by_id(existing.id, changes)
        await self.uow.refresh(existing)
        return existing
