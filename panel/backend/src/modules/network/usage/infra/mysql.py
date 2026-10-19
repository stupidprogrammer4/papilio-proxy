from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select, tuple_
from sqlmodel import col

from src.modules.network.usage.domain.models import (
    UsageEventModel,
    UsageGrantModel,
)
from src.modules.network.usage.domain.results import (
    UsageEventIdentity,
    UsageGrantAllocationKey,
)
from src.modules.network.usage.infra.tables import (
    UsageEventTable,
    UsageGrantTable,
)


class UsageGrantRepository(MySQLPersistenceRepository[UsageGrantModel]):
    table = UsageGrantTable

    async def locked_many(self, ids: list[int]) -> list[UsageGrantModel]:
        selected = sorted(set(ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(UsageGrantTable)
            .where(col(UsageGrantTable.id).in_(selected))
            .order_by(col(UsageGrantTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def allocations_many(
        self, keys: list[UsageGrantAllocationKey]
    ) -> list[UsageGrantModel]:
        if not keys:
            return []
        result = await self.uow.execute(
            select(UsageGrantTable)
            .where(
                tuple_(
                    col(UsageGrantTable.profile_id),
                    col(UsageGrantTable.generation),
                    col(UsageGrantTable.request_key),
                ).in_(
                    [
                        (key.profile_id, key.generation, key.request_key)
                        for key in keys
                    ]
                )
            )
            .order_by(col(UsageGrantTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def create_many(self, rows: list[UsageGrantModel]) -> None:
        columns = {
            name: UsageGrantTable.__table__.c[name]
            for name in (
                "subscription_id",
                "profile_id",
                "node_id",
                "generation",
                "configuration_revision",
                "request_key",
                "mode",
                "allocated_bytes",
                "valid_until",
                "installed_revision_id",
                "process_epoch",
            )
        }
        await self.bulk_insert(rows, insert_columns=columns)

    async def change_many(
        self, rows: list[UsageGrantModel]
    ) -> list[UsageGrantModel]:
        if not rows:
            return []
        columns = {
            name: UsageGrantTable.__table__.c[name]
            for name in (
                "upload_bytes",
                "download_bytes",
                "sequence",
                "sampled_at",
                "is_closed",
            )
        }
        await self.bulk_update(rows, update_columns=columns)
        changed = await self.locked_many([row.id for row in rows])
        return changed

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

    async def create_many(self, rows: list[UsageEventModel]) -> None:
        if not rows:
            return
        columns = {
            name: UsageEventTable.__table__.c[name]
            for name in (
                "grant_id",
                "subscription_id",
                "node_id",
                "generation",
                "event_id",
                "payload_hash",
                "sequence",
                "upload_bytes",
                "download_bytes",
                "delta_bytes",
                "delta_upload_bytes",
                "delta_download_bytes",
                "final",
                "sampled_at",
            )
        }
        await self.bulk_insert(rows, insert_columns=columns)

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

    async def by_identities_many(
        self, identities: list[UsageEventIdentity]
    ) -> list[UsageEventModel]:
        if not identities:
            return []
        result = await self.uow.execute(
            select(UsageEventTable)
            .where(
                tuple_(
                    col(UsageEventTable.node_id),
                    col(UsageEventTable.event_id),
                ).in_([(item.node_id, item.event_id) for item in identities])
            )
            .order_by(col(UsageEventTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())
