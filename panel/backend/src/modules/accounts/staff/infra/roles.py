from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import delete, func, or_, select
from sqlmodel import col

from src.modules.accounts.staff.domain.roles import (
    RoleModel,
    RoleRevisionModel,
    StaffRoleChangeModel,
)
from src.modules.accounts.staff.infra.tables import (
    RoleRevisionTable,
    RoleTable,
    StaffRoleChangeTable,
    StaffRoleTable,
)


class RoleRepository(MySQLPersistenceRepository[RoleModel]):
    table = RoleTable

    async def locked(self, id: int) -> RoleModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def selected(self, ids: list[int]) -> list[RoleModel]:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id).in_(ids))
            .order_by(col(self.table.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def page(
        self, q: str | None, is_active: bool | None, offset: int, limit: int
    ) -> PagedType[RoleModel]:
        query = select(self.table)
        if q:
            query = query.where(
                or_(
                    func.lower(col(self.table.code)).like(f"%{q.lower()}%"),
                    col(self.table.title).like(f"%{q}%"),
                )
            )
        if is_active is not None:
            query = query.where(col(self.table.is_active) == is_active)
        result = await fetch_page(
            self.uow,
            query.order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result


class RoleRevisionRepository(MySQLPersistenceRepository[RoleRevisionModel]):
    table = RoleRevisionTable

    async def page(
        self, id: int, offset: int, limit: int
    ) -> PagedType[RoleRevisionModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.role_id) == id)
            .order_by(col(self.table.revision).desc()),
            offset=offset,
            limit=limit,
        )
        return result


class StaffRoleRepository:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def replace(self, id: int, role_ids: list[int]) -> None:
        await self.uow.execute(
            delete(StaffRoleTable).where(col(StaffRoleTable.staff_id) == id)
        )
        self.uow.session.add_all(
            [
                StaffRoleTable(staff_id=id, role_id=role_id)
                for role_id in role_ids
            ]
        )
        await self.uow.flush()


class StaffRoleChangeRepository(
    MySQLPersistenceRepository[StaffRoleChangeModel]
):
    table = StaffRoleChangeTable

    async def page(
        self, id: int, offset: int, limit: int
    ) -> PagedType[StaffRoleChangeModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.target_staff_id) == id)
            .order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result
