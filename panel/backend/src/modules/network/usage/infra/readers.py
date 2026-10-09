from datetime import datetime

from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import case, func, select
from sqlmodel import col

from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.network.usage.domain.models import UsageEventModel
from src.modules.network.usage.domain.results import (
    ProfileUsageAssignment,
    UsageSummary,
)
from src.modules.network.usage.infra.tables import (
    UsageEventTable,
    UsageGrantTable,
)


class UsageFactsReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def assignment(
        self, profile_id: int, node_id: int, lock: bool = False
    ) -> ProfileUsageAssignment | None:
        statement = (
            select(ProfileTable, ConfigurationTable)
            .join(
                ConfigurationTable,
                col(ConfigurationTable.id)
                == col(ProfileTable.configuration_id),
            )
            .where(
                col(ProfileTable.id) == profile_id,
                col(ConfigurationTable.node_id) == node_id,
            )
        )
        if lock:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(statement)
        row = result.one_or_none()
        return (
            None
            if row is None
            else ProfileUsageAssignment(
                row.ProfileTable, row.ConfigurationTable
            )
        )

    async def reserved_bytes(
        self, subscription_id: int, generation: int, modes: list[str]
    ) -> int:
        remaining = (
            col(UsageGrantTable.allocated_bytes)
            - col(UsageGrantTable.upload_bytes)
            - col(UsageGrantTable.download_bytes)
        )
        result = await self.uow.execute(
            select(
                func.coalesce(
                    func.sum(case((remaining > 0, remaining), else_=0)), 0
                )
            )
            .where(
                col(UsageGrantTable.subscription_id) == subscription_id,
                col(UsageGrantTable.generation) == generation,
                col(UsageGrantTable.mode).in_(modes),
                col(UsageGrantTable.is_closed).is_(False),
            )
            .with_for_update()
        )
        return int(result.scalar_one())

    async def has_open_profile(self, profile_id: int, generation: int) -> bool:
        result = await self.uow.execute(
            select(func.count(col(UsageGrantTable.id)))
            .where(
                col(UsageGrantTable.profile_id) == profile_id,
                col(UsageGrantTable.generation) == generation,
                col(UsageGrantTable.is_closed).is_(False),
            )
            .with_for_update()
        )
        return bool(result.scalar_one())

    def _events(
        self,
        subscription_id: int | None,
        node_id: int | None,
        generation: int | None,
        since: datetime | None,
        until: datetime | None,
    ):
        statement = select(UsageEventTable)
        if subscription_id is not None:
            statement = statement.where(
                col(UsageEventTable.subscription_id) == subscription_id
            )
        if node_id is not None:
            statement = statement.where(
                col(UsageEventTable.node_id) == node_id
            )
        if generation is not None:
            statement = statement.where(
                col(UsageEventTable.generation) == generation
            )
        if since is not None:
            statement = statement.where(
                col(UsageEventTable.sampled_at) >= since
            )
        if until is not None:
            statement = statement.where(
                col(UsageEventTable.sampled_at) <= until
            )
        return statement

    async def events(
        self,
        subscription_id: int | None,
        node_id: int | None,
        generation: int | None,
        since: datetime | None,
        until: datetime | None,
        offset: int,
        limit: int,
    ) -> PagedType[UsageEventModel]:
        statement = self._events(
            subscription_id, node_id, generation, since, until
        ).order_by(
            col(UsageEventTable.sampled_at).desc(),
            col(UsageEventTable.id).desc(),
        )
        result = await fetch_page(
            self.uow, statement, offset=offset, limit=limit
        )
        return result

    async def summary(
        self,
        subscription_id: int | None,
        node_id: int | None,
        generation: int | None,
        since: datetime | None,
        until: datetime | None,
    ) -> UsageSummary:
        statement = self._events(
            subscription_id, node_id, generation, since, until
        ).subquery()
        result = await self.uow.execute(
            select(
                func.coalesce(func.sum(statement.c.delta_upload_bytes), 0),
                func.coalesce(func.sum(statement.c.delta_download_bytes), 0),
                func.coalesce(func.sum(statement.c.delta_bytes), 0),
                func.count(statement.c.id),
            )
        )
        row = result.one()
        return UsageSummary(
            upload_bytes=int(row[0]),
            download_bytes=int(row[1]),
            total_bytes=int(row[2]),
            sample_count=int(row[3]),
        )
