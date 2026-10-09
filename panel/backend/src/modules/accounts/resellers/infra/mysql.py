from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import delete, func, select
from sqlmodel import col

from src.modules.accounts.resellers.domain.models import (
    ResellerAccountChangeModel,
    ResellerAccountModel,
    ResellerChangeModel,
    ResellerCustomerModel,
    ResellerModel,
    ResellerSessionModel,
)
from src.modules.accounts.resellers.infra.tables import (
    ResellerAccountChangeTable,
    ResellerAccountTable,
    ResellerChangeTable,
    ResellerCustomerTable,
    ResellerSessionTable,
    ResellerTable,
)


class ResellerRepository(MySQLPersistenceRepository[ResellerModel]):
    table = ResellerTable

    async def locked(self, id: int) -> ResellerModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def page(
        self, q: str | None, offset: int, limit: int
    ) -> PagedType[ResellerModel]:
        query = select(self.table)
        if q:
            query = query.where(
                col(self.table.title).like(f"%{q}%")
                | col(self.table.code).like(f"%{q}%")
            )
        result = await fetch_page(
            self.uow,
            query.order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result


class ResellerAccountRepository(
    MySQLPersistenceRepository[ResellerAccountModel]
):
    table = ResellerAccountTable

    async def by_username(self, username: str) -> ResellerAccountModel | None:
        result = await self.uow.execute(
            select(self.table).where(col(self.table.username) == username)
        )
        return result.scalar_one_or_none()

    async def owned(
        self, reseller_id: int, id: int, lock: bool = False
    ) -> ResellerAccountModel | None:
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

    async def active(
        self, reseller_id: int, limit: int
    ) -> list[ResellerAccountModel]:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.reseller_id) == reseller_id,
                col(self.table.is_active).is_(True),
            )
            .order_by(col(self.table.id))
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def page(
        self, reseller_id: int, q: str | None, offset: int, limit: int
    ) -> PagedType[ResellerAccountModel]:
        query = select(self.table).where(
            col(self.table.reseller_id) == reseller_id
        )
        if q:
            query = query.where(col(self.table.username).like(f"%{q}%"))
        result = await fetch_page(
            self.uow,
            query.order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result


class ResellerSessionRepository:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def create(self, data: ResellerSessionModel) -> None:
        self.uow.session.add(ResellerSessionTable(**data.model_dump()))
        await self.uow.flush()

    async def active(
        self, account_id: int, now: datetime, limit: int
    ) -> list[ResellerSessionModel]:
        result = await self.uow.execute(
            select(ResellerSessionTable)
            .where(
                col(ResellerSessionTable.account_id) == account_id,
                col(ResellerSessionTable.expires_at) > now,
            )
            .order_by(
                col(ResellerSessionTable.expires_at),
                col(ResellerSessionTable.token_hash),
            )
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def remove(self, token_hash: str) -> None:
        await self.uow.execute(
            delete(ResellerSessionTable).where(
                col(ResellerSessionTable.token_hash) == token_hash
            )
        )

    async def remove_many(self, token_hashes: list[str]) -> None:
        await self.uow.execute(
            delete(ResellerSessionTable).where(
                col(ResellerSessionTable.token_hash).in_(token_hashes)
            )
        )

    async def remove_obsolete(
        self,
        account_id: int,
        account_revision: int,
        reseller_access_revision: int,
        now: datetime,
    ) -> None:
        await self.uow.execute(
            delete(ResellerSessionTable).where(
                col(ResellerSessionTable.account_id) == account_id,
                (col(ResellerSessionTable.expires_at) <= now)
                | (
                    col(ResellerSessionTable.account_revision)
                    != account_revision
                )
                | (
                    col(ResellerSessionTable.reseller_access_revision)
                    != reseller_access_revision
                ),
            )
        )


class ResellerCustomerRepository:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def create(self, data: ResellerCustomerModel) -> None:
        self.uow.session.add(ResellerCustomerTable(**data.model_dump()))
        await self.uow.flush()

    async def count_locked(self, reseller_id: int) -> int:
        result = await self.uow.execute(
            select(func.count())
            .select_from(ResellerCustomerTable)
            .where(col(ResellerCustomerTable.reseller_id) == reseller_id)
            .with_for_update()
        )
        return result.scalar_one()


class ResellerChangeRepository(
    MySQLPersistenceRepository[ResellerChangeModel]
):
    table = ResellerChangeTable

    async def page(
        self, reseller_id: int, offset: int, limit: int
    ) -> PagedType[ResellerChangeModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.reseller_id) == reseller_id)
            .order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result


class ResellerAccountChangeRepository(
    MySQLPersistenceRepository[ResellerAccountChangeModel]
):
    table = ResellerAccountChangeTable

    async def page(
        self, reseller_id: int, account_id: int, offset: int, limit: int
    ) -> PagedType[ResellerAccountChangeModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(
                col(self.table.reseller_id) == reseller_id,
                col(self.table.account_id) == account_id,
            )
            .order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result
