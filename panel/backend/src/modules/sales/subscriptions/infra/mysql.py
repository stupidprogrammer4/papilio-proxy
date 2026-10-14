from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.sales.subscriptions.domain.models import (
    SubscriptionControlModel,
    SubscriptionModel,
)
from src.modules.sales.subscriptions.domain.results import (
    SubscriptionUsageUpdate,
)
from src.modules.sales.subscriptions.infra.tables import (
    SubscriptionControlTable,
    SubscriptionTable,
)


class SubscriptionRepository(MySQLPersistenceRepository[SubscriptionModel]):
    table = SubscriptionTable

    async def locked_many(self, ids: list[int]) -> list[SubscriptionModel]:
        selected = sorted(set(ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(SubscriptionTable)
            .where(col(SubscriptionTable.id).in_(selected))
            .order_by(col(SubscriptionTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def update_used_many(
        self, updates: list[SubscriptionUsageUpdate]
    ) -> None:
        if not updates:
            return
        rows = [
            SubscriptionModel.patch(
                id=item.subscription_id, used_bytes=item.used_bytes
            )
            for item in updates
        ]
        await self.bulk_update(
            rows,
            update_columns={
                "used_bytes": SubscriptionTable.__table__.c.used_bytes,
            },
        )

    async def by_purchase_key(self, key: str) -> SubscriptionModel | None:
        result = await self.uow.execute(
            select(SubscriptionTable).where(
                col(SubscriptionTable.purchase_key) == key
            )
        )
        return result.scalar_one_or_none()

    async def locked_by_purchase_key(
        self, key: str
    ) -> SubscriptionModel | None:
        result = await self.uow.execute(
            select(SubscriptionTable)
            .where(col(SubscriptionTable.purchase_key) == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def locked(self, id: int) -> SubscriptionModel | None:
        result = await self.uow.execute(
            select(SubscriptionTable)
            .where(col(SubscriptionTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def update_existing(
        self, existing: SubscriptionModel, changes: SubscriptionModel
    ) -> SubscriptionModel:
        await self.update_row_by_id(existing.id, changes)
        await self.uow.refresh(existing)
        return existing

    async def due_ids(
        self,
        now: datetime,
        limit: int,
        auto_renew: bool,
        statuses: list[str],
        include_quota: bool = False,
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(SubscriptionTable.id))
            .where(
                (col(SubscriptionTable.expires_at) <= now)
                | (
                    (
                        col(SubscriptionTable.used_bytes)
                        >= col(SubscriptionTable.quota_bytes)
                    )
                    if include_quota
                    else False
                )
            )
            .where(col(SubscriptionTable.auto_renew).is_(auto_renew))
            .where(col(SubscriptionTable.status).in_(statuses))
            .order_by(
                col(SubscriptionTable.renewal_checked_at),
                col(SubscriptionTable.expires_at),
                col(SubscriptionTable.id),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def retirement_ids(
        self, now: datetime, limit: int, statuses: list[str]
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(SubscriptionTable.id))
            .where(
                col(SubscriptionTable.status).in_(statuses),
                (col(SubscriptionTable.expires_at) <= now)
                | (
                    col(SubscriptionTable.used_bytes)
                    >= col(SubscriptionTable.quota_bytes)
                ),
            )
            .order_by(
                col(SubscriptionTable.lifecycle_checked_at),
                col(SubscriptionTable.id),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def page(
        self,
        customer_id: int | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> PagedType[SubscriptionModel]:
        query = select(SubscriptionTable)
        if customer_id is not None:
            query = query.where(
                col(SubscriptionTable.customer_id) == customer_id
            )
        if status is not None:
            query = query.where(col(SubscriptionTable.status) == status)
        query = query.order_by(col(SubscriptionTable.id).desc())
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class SubscriptionControlRepository(
    MySQLPersistenceRepository[SubscriptionControlModel]
):
    table = SubscriptionControlTable

    async def by_request(
        self, request_key: str
    ) -> SubscriptionControlModel | None:
        result = await self.uow.execute(
            select(SubscriptionControlTable)
            .where(col(SubscriptionControlTable.request_key) == request_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def page(
        self, subscription_id: int, offset: int, limit: int
    ) -> PagedType[SubscriptionControlModel]:
        result = await fetch_page(
            self.uow,
            select(SubscriptionControlTable)
            .where(
                col(SubscriptionControlTable.subscription_id)
                == subscription_id
            )
            .order_by(col(SubscriptionControlTable.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result
