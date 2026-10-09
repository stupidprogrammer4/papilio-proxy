from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import or_, select, update
from sqlmodel import col

from src.modules.network.ip_limits.domain.dtos import IpSessionCriteria
from src.modules.network.ip_limits.domain.models import (
    IpLimitPolicyModel,
    IpSessionModel,
)
from src.modules.network.ip_limits.infra.tables import (
    IpLimitPolicyTable,
    IpSessionTable,
)


class IpLimitPolicyRepository(MySQLPersistenceRepository[IpLimitPolicyModel]):
    table = IpLimitPolicyTable

    async def by_subscription(
        self, subscription_id: int
    ) -> IpLimitPolicyModel | None:
        result = await self.uow.execute(
            select(IpLimitPolicyTable).where(
                col(IpLimitPolicyTable.subscription_id) == subscription_id
            )
        )
        return result.scalar_one_or_none()

    async def locked(self, subscription_id: int) -> IpLimitPolicyModel | None:
        result = await self.uow.execute(
            select(IpLimitPolicyTable)
            .where(col(IpLimitPolicyTable.subscription_id) == subscription_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def change(
        self, existing: IpLimitPolicyModel, data: IpLimitPolicyModel
    ) -> IpLimitPolicyModel:
        await self.update_row_by_id(existing.id, data)
        await self.uow.refresh(existing)
        return existing


class IpSessionRepository(MySQLPersistenceRepository[IpSessionModel]):
    table = IpSessionTable

    async def by_ip(
        self, subscription_id: int, source_ip: str
    ) -> IpSessionModel | None:
        result = await self.uow.execute(
            select(IpSessionTable)
            .where(
                col(IpSessionTable.subscription_id) == subscription_id,
                col(IpSessionTable.source_ip) == source_ip,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def change(
        self, existing: IpSessionModel, data: IpSessionModel
    ) -> IpSessionModel:
        await self.update_row_by_id(existing.id, data)
        await self.uow.refresh(existing)
        return existing

    async def expire_subscription(
        self, subscription_id: int, until: datetime
    ) -> None:
        await self.uow.execute(
            update(IpSessionTable)
            .where(col(IpSessionTable.subscription_id) == subscription_id)
            .values(expires_at=until)
        )

    async def active_sessions(
        self, subscription_id: int, now: datetime, limit: int
    ) -> list[IpSessionModel]:
        result = await self.uow.execute(
            select(IpSessionTable)
            .where(
                col(IpSessionTable.subscription_id) == subscription_id,
                col(IpSessionTable.expires_at) > now,
                or_(
                    col(IpSessionTable.blocked_until).is_(None),
                    col(IpSessionTable.blocked_until) <= now,
                ),
            )
            .order_by(col(IpSessionTable.id))
            .limit(limit)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def page(
        self,
        subscription_id: int,
        criteria: IpSessionCriteria,
        offset: int,
        limit: int,
    ) -> PagedType[IpSessionModel]:
        query = select(IpSessionTable).where(
            col(IpSessionTable.subscription_id) == subscription_id
        )
        if criteria.source_ip_query:
            query = query.where(
                col(IpSessionTable.source_ip).contains(
                    criteria.source_ip_query, autoescape=True
                )
            )
        if criteria.blocked_after is not None:
            query = query.where(
                col(IpSessionTable.blocked_until) > criteria.blocked_after
            )
        if criteria.unblocked_at_or_before is not None:
            query = query.where(
                or_(
                    col(IpSessionTable.blocked_until).is_(None),
                    col(IpSessionTable.blocked_until)
                    <= criteria.unblocked_at_or_before,
                )
            )
        if criteria.expires_after is not None:
            query = query.where(
                col(IpSessionTable.expires_at) > criteria.expires_after
            )
        if criteria.expires_at_or_before is not None:
            query = query.where(
                col(IpSessionTable.expires_at) <= criteria.expires_at_or_before
            )
        result = await fetch_page(
            self.uow,
            query.order_by(
                col(IpSessionTable.last_seen_at).desc(),
                col(IpSessionTable.id).desc(),
            ),
            offset=offset,
            limit=limit,
        )
        return result
