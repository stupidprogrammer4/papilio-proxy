from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import delete, func, select
from sqlmodel import col

from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.infra.tables import (
    StaffGrantTable,
    StaffSessionTable,
    StaffTable,
)


class StaffRepository(MySQLPersistenceRepository[StaffModel]):
    table = StaffTable

    async def by_username(self, username: str) -> StaffModel | None:
        result = await self.uow.execute(
            select(StaffTable).where(col(StaffTable.username) == username)
        )
        return result.scalar_one_or_none()

    async def locked_by_username(self, username: str) -> StaffModel | None:
        result = await self.uow.execute(
            select(StaffTable)
            .where(col(StaffTable.username) == username)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def grants(self, staff_id: int) -> frozenset[str]:
        result = await self.uow.execute(
            select(col(StaffGrantTable.scope)).where(
                col(StaffGrantTable.staff_id) == staff_id
            )
        )
        return frozenset(result.scalars().all())

    async def add_grant(self, staff_id: int, scope: str) -> None:
        self.uow.session.add(StaffGrantTable(staff_id=staff_id, scope=scope))
        await self.uow.flush()

    async def store_session(
        self,
        token_hash: str,
        staff_id: int,
        csrf_token: str,
        expires_at: datetime,
    ) -> None:
        self.uow.session.add(
            StaffSessionTable(
                token_hash=token_hash,
                staff_id=staff_id,
                csrf_token=csrf_token,
                expires_at=expires_at,
            )
        )
        await self.uow.flush()

    async def remove_session(self, token_hash: str) -> None:
        await self.uow.execute(
            delete(StaffSessionTable).where(
                col(StaffSessionTable.token_hash) == token_hash
            )
        )

    async def page(
        self, q: str | None, offset: int, limit: int
    ) -> PagedType[StaffModel]:
        query = select(StaffTable)
        if q:
            query = query.where(
                func.lower(col(StaffTable.username)).like(f"%{q.lower()}%")
            )
        result = await fetch_page(
            self.uow,
            query.order_by(col(StaffTable.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result

    async def replace_grants(self, staff_id: int, scopes: list[str]) -> None:
        await self.uow.execute(
            delete(StaffGrantTable).where(
                col(StaffGrantTable.staff_id) == staff_id
            )
        )
        self.uow.session.add_all(
            [
                StaffGrantTable(staff_id=staff_id, scope=scope)
                for scope in scopes
            ]
        )
        await self.uow.flush()

    async def revoke_sessions(self, staff_id: int) -> None:
        await self.uow.execute(
            delete(StaffSessionTable).where(
                col(StaffSessionTable.staff_id) == staff_id
            )
        )
