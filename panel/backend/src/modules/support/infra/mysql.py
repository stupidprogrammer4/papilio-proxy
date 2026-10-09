from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.support.domain.models import (
    SupportMessageModel,
    SupportStateChangeModel,
    SupportTicketModel,
)
from src.modules.support.infra.tables import (
    SupportMessageTable,
    SupportStateChangeTable,
    SupportTicketTable,
)


class SupportTicketRepository(MySQLPersistenceRepository[SupportTicketModel]):
    table = SupportTicketTable

    async def locked(self, id: int) -> SupportTicketModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def by_request(
        self, customer_id: int, request_key: str
    ) -> SupportTicketModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.customer_id) == customer_id,
                col(self.table.request_key) == request_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def owned(
        self, id: int, customer_id: int
    ) -> SupportTicketModel | None:
        result = await self.uow.execute(
            select(self.table).where(
                col(self.table.id) == id,
                col(self.table.customer_id) == customer_id,
            )
        )
        return result.scalar_one_or_none()

    async def open_ids(
        self, customer_id: int, closed_status: str, limit: int
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(self.table.id))
            .where(
                col(self.table.customer_id) == customer_id,
                col(self.table.status) != closed_status,
            )
            .order_by(col(self.table.id))
            .limit(limit)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def page(
        self,
        q: str | None,
        status: str | None,
        customer_id: int | None,
        offset: int,
        limit: int,
    ) -> PagedType[SupportTicketModel]:
        query = select(self.table)
        if q:
            query = query.where(col(self.table.subject).like(f"%{q}%"))
        if status is not None:
            query = query.where(col(self.table.status) == status)
        if customer_id is not None:
            query = query.where(col(self.table.customer_id) == customer_id)
        result = await fetch_page(
            self.uow,
            query.order_by(
                col(self.table.updated_at).desc(), col(self.table.id).desc()
            ),
            offset=offset,
            limit=limit,
        )
        return result

    async def customer_page(
        self,
        customer_id: int,
        q: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> PagedType[SupportTicketModel]:
        query = select(self.table).where(
            col(self.table.customer_id) == customer_id
        )
        if q:
            query = query.where(col(self.table.subject).like(f"%{q}%"))
        if status is not None:
            query = query.where(col(self.table.status) == status)
        result = await fetch_page(
            self.uow,
            query.order_by(
                col(self.table.updated_at).desc(), col(self.table.id).desc()
            ),
            offset=offset,
            limit=limit,
        )
        return result


class SupportMessageRepository(
    MySQLPersistenceRepository[SupportMessageModel]
):
    table = SupportMessageTable

    async def by_request(
        self, id: int, request_key: str
    ) -> SupportMessageModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.ticket_id) == id,
                col(self.table.request_key) == request_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def ids(self, ticket_id: int, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(self.table.id))
            .where(col(self.table.ticket_id) == ticket_id)
            .order_by(col(self.table.id))
            .limit(limit)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def page(
        self, ticket_id: int, offset: int, limit: int
    ) -> PagedType[SupportMessageModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.ticket_id) == ticket_id)
            .order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result


class SupportStateChangeRepository(
    MySQLPersistenceRepository[SupportStateChangeModel]
):
    table = SupportStateChangeTable

    async def page(
        self, ticket_id: int, offset: int, limit: int
    ) -> PagedType[SupportStateChangeModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.ticket_id) == ticket_id)
            .order_by(col(self.table.revision).desc()),
            offset=offset,
            limit=limit,
        )
        return result
