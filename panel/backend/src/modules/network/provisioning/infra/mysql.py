from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select, tuple_, update
from sqlmodel import col

from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.network.provisioning.domain.results import (
    ProvisionGenerationKey,
)
from src.modules.network.provisioning.infra.tables import (
    ProvisionRequestTable,
    ProvisionTaskTable,
)


class ProvisionRequestRepository(
    MySQLPersistenceRepository[ProvisionRequestModel]
):
    table = ProvisionRequestTable

    async def locked(self, id: int) -> ProvisionRequestModel | None:
        result = await self.uow.execute(
            select(ProvisionRequestTable)
            .where(col(ProvisionRequestTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def locked_many(self, ids: list[int]) -> list[ProvisionRequestModel]:
        selected = sorted(set(ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(ProvisionRequestTable)
            .where(col(ProvisionRequestTable.id).in_(selected))
            .order_by(col(ProvisionRequestTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def by_generation(
        self, subscription_id: int, generation: int
    ) -> ProvisionRequestModel | None:
        result = await self.uow.execute(
            select(ProvisionRequestTable)
            .where(
                col(ProvisionRequestTable.subscription_id) == subscription_id,
                col(ProvisionRequestTable.generation) == generation,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def by_generations(
        self, keys: list[ProvisionGenerationKey]
    ) -> list[ProvisionRequestModel]:
        if not keys:
            return []
        result = await self.uow.execute(
            select(ProvisionRequestTable)
            .where(
                tuple_(
                    col(ProvisionRequestTable.subscription_id),
                    col(ProvisionRequestTable.generation),
                ).in_([(key.subscription_id, key.generation) for key in keys])
            )
            .order_by(
                col(ProvisionRequestTable.subscription_id),
                col(ProvisionRequestTable.generation),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def change(
        self, row: ProvisionRequestModel, patch: ProvisionRequestModel
    ) -> ProvisionRequestModel:
        await self.update_row_by_id(row.id, patch)
        await self.uow.refresh(row)
        return row

    async def change_many(self, rows: list[ProvisionRequestModel]) -> None:
        if not rows:
            return
        columns = {
            name: ProvisionRequestTable.__table__.c[name]
            for name in (
                "completion",
                "state",
                "reason_code",
                "checked_at",
                "activated_at",
                "cancellation_reason",
                "cancelled_by_staff_id",
            )
        }
        await self.bulk_update(rows, update_columns=columns)

    async def due_ids(
        self, before: datetime, states: list[str], limit: int
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(ProvisionRequestTable.id))
            .where(
                col(ProvisionRequestTable.state).in_(states),
                (
                    col(ProvisionRequestTable.checked_at).is_(None)
                    | (col(ProvisionRequestTable.checked_at) <= before)
                ),
            )
            .order_by(
                col(ProvisionRequestTable.checked_at),
                col(ProvisionRequestTable.id),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def page(
        self,
        subscription_id: int | None,
        state: str | None,
        offset: int,
        limit: int,
    ) -> PagedType[ProvisionRequestModel]:
        query = select(ProvisionRequestTable).order_by(
            col(ProvisionRequestTable.id).desc()
        )
        if subscription_id is not None:
            query = query.where(
                col(ProvisionRequestTable.subscription_id) == subscription_id
            )
        if state is not None:
            query = query.where(col(ProvisionRequestTable.state) == state)
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class ProvisionTaskRepository(MySQLPersistenceRepository[ProvisionTaskModel]):
    table = ProvisionTaskTable

    async def locked(self, id: int) -> ProvisionTaskModel | None:
        result = await self.uow.execute(
            select(ProvisionTaskTable)
            .where(col(ProvisionTaskTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def locked_many(self, ids: list[int]) -> list[ProvisionTaskModel]:
        selected = sorted(set(ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(ProvisionTaskTable)
            .where(col(ProvisionTaskTable.id).in_(selected))
            .order_by(col(ProvisionTaskTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def change_many(self, rows: list[ProvisionTaskModel]) -> None:
        if not rows:
            return
        columns = {
            name: ProvisionTaskTable.__table__.c[name]
            for name in (
                "installed_revision_id",
                "membership_sha256",
                "ack_sha256",
                "state",
                "attempts",
                "claim_hash",
                "claim_until",
                "last_outcome",
                "acknowledged_at",
            )
        }
        await self.bulk_update(rows, update_columns=columns)

    async def change_managed_many(
        self, rows: list[ProvisionTaskModel]
    ) -> None:
        if not rows:
            return
        columns = {
            name: ProvisionTaskTable.__table__.c[name]
            for name in (
                "installed_revision_id",
                "membership_sha256",
                "ack_sha256",
                "state",
                "attempts",
                "claim_hash",
                "claim_until",
                "last_outcome",
                "acknowledged_at",
                "error_code",
                "action",
                "available_at",
            )
        }
        await self.bulk_update(rows, update_columns=columns)

    async def for_request(
        self, request_id: int, limit: int
    ) -> list[ProvisionTaskModel]:
        result = await self.uow.execute(
            select(ProvisionTaskTable)
            .where(col(ProvisionTaskTable.request_id) == request_id)
            .order_by(col(ProvisionTaskTable.id))
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def for_requests_many(
        self, request_ids: list[int]
    ) -> list[ProvisionTaskModel]:
        selected = sorted(set(request_ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(ProvisionTaskTable)
            .where(col(ProvisionTaskTable.request_id).in_(selected))
            .order_by(
                col(ProvisionTaskTable.request_id),
                col(ProvisionTaskTable.id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def create_targets(self, rows: list[ProvisionTaskModel]) -> None:
        columns = {
            name: ProvisionTaskTable.__table__.c[name]
            for name in (
                "configuration_revision",
                "request_id",
                "configuration_id",
                "profile_id",
                "node_id",
                "action",
                "state",
                "attempts",
                "available_at",
                "encrypted_payload",
            )
        }
        await self.bulk_insert(rows, insert_columns=columns)

    async def replace_payloads(self, rows: list[ProvisionTaskModel]) -> None:
        if not rows:
            return
        columns = {
            name: ProvisionTaskTable.__table__.c[name]
            for name in (
                "configuration_revision",
                "encrypted_payload",
                "state",
                "attempts",
                "claim_hash",
                "claim_until",
                "last_outcome",
                "acknowledged_at",
                "error_code",
                "available_at",
            )
        }
        await self.bulk_update(rows, update_columns=columns)

    async def change(
        self, row: ProvisionTaskModel, patch: ProvisionTaskModel
    ) -> ProvisionTaskModel:
        await self.update_row_by_id(row.id, patch)
        await self.uow.refresh(row)
        return row

    async def update_request_tasks(
        self,
        request_id: int,
        states: list[str] | None,
        changes: ProvisionTaskModel,
    ) -> None:
        statement = update(ProvisionTaskTable).where(
            col(ProvisionTaskTable.request_id) == request_id
        )
        if states is not None:
            statement = statement.where(
                col(ProvisionTaskTable.state).in_(states)
            )
        await self.uow.execute(
            statement.values(**changes.model_dump(exclude_unset=True))
        )

    async def page(
        self,
        request_id: int | None,
        node_id: int | None,
        states: list[str] | None,
        offset: int,
        limit: int,
    ) -> PagedType[ProvisionTaskModel]:
        query = select(ProvisionTaskTable).order_by(col(ProvisionTaskTable.id))
        if request_id is not None:
            query = query.where(
                col(ProvisionTaskTable.request_id) == request_id
            )
        if node_id is not None:
            query = query.where(col(ProvisionTaskTable.node_id) == node_id)
        if states is not None:
            query = query.where(col(ProvisionTaskTable.state).in_(states))
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
