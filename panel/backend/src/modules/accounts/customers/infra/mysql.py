from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlmodel import col

from src.modules.accounts.customers.domain.models import (
    CustomerAccessChangeModel,
    CustomerModel,
)
from src.modules.accounts.customers.infra.tables import (
    CustomerAccessChangeTable,
    CustomerTable,
)


class CustomerRepository(MySQLPersistenceRepository[CustomerModel]):
    table = CustomerTable

    async def locked(self, id: int) -> CustomerModel | None:
        result = await self.uow.execute(
            select(CustomerTable)
            .where(col(CustomerTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def locked_many(
        self, ids: list[int], ascending: bool
    ) -> list[CustomerModel]:
        ordering = (
            col(CustomerTable.id).asc()
            if ascending
            else col(CustomerTable.id).desc()
        )
        result = await self.uow.execute(
            select(CustomerTable)
            .where(col(CustomerTable.id).in_(ids))
            .order_by(ordering)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars())

    async def by_telegram_id(self, telegram_id: int) -> CustomerModel | None:
        result = await self.uow.execute(
            select(CustomerTable).where(
                col(CustomerTable.telegram_id) == telegram_id
            )
        )
        return result.scalar_one_or_none()

    async def ensure_telegram(self, customer: CustomerModel) -> CustomerModel:
        if customer.telegram_id is None:
            raise ValueError("A persisted Telegram identity is required")
        await self.uow.execute(
            insert(CustomerTable)
            .values(
                **customer.model_dump(exclude_unset=True),
            )
            .prefix_with("IGNORE")
        )
        result = await self.by_telegram_id(customer.telegram_id)
        assert result is not None
        return result

    async def hold_pending_ids(self, pending: bool, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(CustomerTable.id))
            .where(col(CustomerTable.service_hold_pending).is_(pending))
            .order_by(col(CustomerTable.updated_at), col(CustomerTable.id))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def page(
        self, q: str | None, offset: int, limit: int
    ) -> PagedType[CustomerModel]:
        query = select(CustomerTable)
        if q:
            query = query.where(
                func.lower(col(CustomerTable.display_name)).like(
                    f"%{q.lower()}%"
                )
            )
        query = query.order_by(col(CustomerTable.id).desc())
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class CustomerAccessChangeRepository(
    MySQLPersistenceRepository[CustomerAccessChangeModel]
):
    table = CustomerAccessChangeTable

    async def by_request(
        self, request_key: str
    ) -> CustomerAccessChangeModel | None:
        result = await self.uow.execute(
            select(CustomerAccessChangeTable)
            .where(col(CustomerAccessChangeTable.request_key) == request_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def page(
        self, customer_id: int, offset: int, limit: int
    ) -> PagedType[CustomerAccessChangeModel]:
        result = await fetch_page(
            self.uow,
            select(CustomerAccessChangeTable)
            .where(col(CustomerAccessChangeTable.customer_id) == customer_id)
            .order_by(col(CustomerAccessChangeTable.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result
