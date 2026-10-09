from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import Select, func, select
from sqlmodel import col

from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.domain.results import (
    RoleMemberCount,
    StaffAccess,
    StoredStaffSession,
)
from src.modules.accounts.staff.domain.roles import RoleModel
from src.modules.accounts.staff.infra.tables import (
    RoleTable,
    StaffGrantTable,
    StaffRoleTable,
    StaffSessionTable,
    StaffTable,
)


class StaffSessionReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def by_token(self, token_hash: str) -> StoredStaffSession | None:
        result = await self.uow.execute(
            select(StaffTable, StaffSessionTable)
            .join(
                StaffSessionTable,
                col(StaffSessionTable.staff_id) == col(StaffTable.id),
            )
            .where(col(StaffSessionTable.token_hash) == token_hash)
        )
        row = result.one_or_none()
        return (
            None
            if row is None
            else StoredStaffSession(
                staff=row.StaffTable, session=row.StaffSessionTable
            )
        )

    async def roles(self, staff_id: int) -> tuple[RoleModel, ...]:
        result = await self.uow.execute(role_selection(staff_id))
        return tuple(result.scalars().all())


class StaffAuthorityReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def access(
        self, staff_id: int, lock: bool = False
    ) -> StaffAccess | None:
        query = select(StaffTable).where(col(StaffTable.id) == staff_id)
        if lock:
            query = query.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(query)
        staff = result.scalar_one_or_none()
        if staff is None:
            return None
        grants = select(col(StaffGrantTable.scope)).where(
            col(StaffGrantTable.staff_id) == staff_id
        )
        if lock:
            grants = grants.with_for_update()
        result = await self.uow.execute(grants)
        direct = frozenset(result.scalars().all())
        roles = role_selection(staff_id)
        if lock:
            roles = roles.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(roles)
        return StaffAccess(staff, direct, tuple(result.scalars().all()))

    async def locked_owners(self) -> list[StaffModel]:
        result = await self.uow.execute(
            select(StaffTable)
            .join(
                StaffGrantTable,
                col(StaffGrantTable.staff_id) == col(StaffTable.id),
            )
            .where(col(StaffGrantTable.scope) == "*")
            .order_by(col(StaffTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def role_members(
        self, role_id: int, limit: int
    ) -> list[StaffAccess]:
        staff_result = await self.uow.execute(
            select(StaffTable)
            .join(
                StaffRoleTable,
                col(StaffRoleTable.staff_id) == col(StaffTable.id),
            )
            .where(col(StaffRoleTable.role_id) == role_id)
            .limit(limit)
            .order_by(col(StaffTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        staff = list(staff_result.scalars().all())
        ids = [item.id for item in staff]
        grants = await self.uow.execute(
            select(StaffGrantTable)
            .where(col(StaffGrantTable.staff_id).in_(ids))
            .with_for_update()
        )
        direct: dict[int, set[str]] = {id: set() for id in ids}
        for grant in grants.scalars().all():
            direct[grant.staff_id].add(grant.scope)
        roles = await self.uow.execute(
            select(col(StaffRoleTable.staff_id), RoleTable)
            .join(RoleTable, col(StaffRoleTable.role_id) == col(RoleTable.id))
            .where(col(StaffRoleTable.staff_id).in_(ids))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assigned: dict[int, list[RoleModel]] = {id: [] for id in ids}
        for row in roles.all():
            assigned[row.staff_id].append(row.RoleTable)
        return [
            StaffAccess(
                item, frozenset(direct[item.id]), tuple(assigned[item.id])
            )
            for item in staff
        ]

    async def member_counts(
        self, role_ids: list[int]
    ) -> list[RoleMemberCount]:
        result = await self.uow.execute(
            select(col(StaffRoleTable.role_id), func.count())
            .where(col(StaffRoleTable.role_id).in_(role_ids))
            .group_by(col(StaffRoleTable.role_id))
        )
        return [RoleMemberCount(row.role_id, row[1]) for row in result.all()]

    async def member_page(
        self, role_id: int, q: str | None, offset: int, limit: int
    ) -> PagedType[StaffModel]:
        query = (
            select(StaffTable)
            .join(
                StaffRoleTable,
                col(StaffRoleTable.staff_id) == col(StaffTable.id),
            )
            .where(col(StaffRoleTable.role_id) == role_id)
        )
        if q:
            query = query.where(
                func.lower(col(StaffTable.username)).like(f"%{q.lower()}%")
            )
        result = await fetch_page(
            self.uow,
            query.order_by(col(StaffTable.id)),
            offset=offset,
            limit=limit,
        )
        return result


def role_selection(staff_id: int) -> Select[tuple[RoleTable]]:
    return (
        select(RoleTable)
        .join(StaffRoleTable, col(StaffRoleTable.role_id) == col(RoleTable.id))
        .where(col(StaffRoleTable.staff_id) == staff_id)
        .order_by(col(RoleTable.id))
    )
