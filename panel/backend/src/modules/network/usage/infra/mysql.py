from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.usage.domain.models import (
    UsageEventModel,
    UsageGrantModel,
)
from src.modules.network.usage.infra.tables import (
    UsageEventTable,
    UsageGrantTable,
)


class UsageGrantRepository(MySQLPersistenceRepository[UsageGrantModel]):
    table = UsageGrantTable

    async def allocation(
        self, profile_id: int, generation: int, request_key: str
    ) -> UsageGrantModel | None:
        result = await self.uow.execute(
            select(UsageGrantTable)
            .where(
                col(UsageGrantTable.profile_id) == profile_id,
                col(UsageGrantTable.generation) == generation,
                col(UsageGrantTable.request_key) == request_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def locked(self, id: int) -> UsageGrantModel | None:
        result = await self.uow.execute(
            select(UsageGrantTable)
            .where(col(UsageGrantTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: UsageGrantModel, changes: UsageGrantModel
    ) -> UsageGrantModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def page(
        self,
        subscription_id: int | None,
        node_id: int | None,
        generation: int | None,
        offset: int,
        limit: int,
    ) -> PagedType[UsageGrantModel]:
        statement = select(UsageGrantTable).order_by(
            col(UsageGrantTable.id).desc()
        )
        if subscription_id is not None:
            statement = statement.where(
                col(UsageGrantTable.subscription_id) == subscription_id
            )
        if node_id is not None:
            statement = statement.where(
                col(UsageGrantTable.node_id) == node_id
            )
        if generation is not None:
            statement = statement.where(
                col(UsageGrantTable.generation) == generation
            )
        result = await fetch_page(
            self.uow, statement, offset=offset, limit=limit
        )
        return result


class UsageEventRepository(MySQLPersistenceRepository[UsageEventModel]):
    table = UsageEventTable

    async def by_identity(
        self, node_id: int, event_id: str
    ) -> UsageEventModel | None:
        result = await self.uow.execute(
            select(UsageEventTable)
            .where(
                col(UsageEventTable.node_id) == node_id,
                col(UsageEventTable.event_id) == event_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
