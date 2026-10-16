from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import or_, select, tuple_
from sqlalchemy.dialects.mysql import insert
from sqlmodel import col

from src.modules.operations.notifications.domain.dtos import (
    CustomerNotificationEvent,
)
from src.modules.operations.notifications.domain.models import (
    NotificationAttemptModel,
    NotificationModel,
    NotificationRecoveryModel,
)
from src.modules.operations.notifications.infra.tables import (
    NotificationAttemptTable,
    NotificationRecoveryTable,
    NotificationTable,
)


class NotificationRepository(MySQLPersistenceRepository[NotificationModel]):
    table = NotificationTable

    async def by_request(
        self, customer_id: int, event_key: str
    ) -> NotificationModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.customer_id) == customer_id,
                col(self.table.event_key) == event_key,
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def by_requests_many(
        self, items: list[CustomerNotificationEvent]
    ) -> list[NotificationModel]:
        identities = sorted(
            {(item.customer_id, item.event.event_key) for item in items}
        )
        if not identities:
            return []
        result = await self.uow.execute(
            select(self.table)
            .where(
                tuple_(
                    col(self.table.customer_id), col(self.table.event_key)
                ).in_(identities)
            )
            .order_by(col(self.table.customer_id), col(self.table.event_key))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def ensure(self, initial: NotificationModel) -> NotificationModel:
        await self.uow.execute(
            insert(self.table)
            .values(**initial.model_dump(exclude_unset=True))
            .prefix_with("IGNORE")
        )
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.customer_id) == initial.customer_id,
                col(self.table.event_key) == initial.event_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def ensure_many(self, initial: list[NotificationModel]) -> None:
        if not initial:
            return
        await self.uow.execute(
            insert(self.table)
            .values([row.model_dump(exclude_unset=True) for row in initial])
            .prefix_with("IGNORE")
        )

    async def locked(self, id: int) -> NotificationModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def update_existing(
        self, row: NotificationModel, changes: NotificationModel
    ) -> NotificationModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def owned(
        self, id: int, customer_id: int
    ) -> NotificationModel | None:
        result = await self.uow.execute(
            select(self.table).where(
                col(self.table.id) == id,
                col(self.table.customer_id) == customer_id,
                col(self.table.inbox_visible).is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def due_ids(
        self,
        now: datetime,
        statuses: tuple[str, ...],
        processing_status: str,
        kinds: tuple[str, ...],
        limit: int,
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(self.table.id))
            .where(
                or_(
                    col(self.table.status).in_(statuses)
                    & col(self.table.kind).in_(kinds)
                    & (col(self.table.next_attempt_at) <= now),
                    (col(self.table.status) == processing_status)
                    & (col(self.table.lease_until) <= now),
                )
            )
            .order_by(col(self.table.next_attempt_at), col(self.table.id))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def page(
        self,
        q: str | None,
        kind: str | None,
        status: str | None,
        is_read: bool | None,
        customer_id: int | None,
        offset: int,
        limit: int,
    ) -> PagedType[NotificationModel]:
        query = select(self.table)
        if q:
            query = query.where(col(self.table.title).like(f"%{q}%"))
        if kind is not None:
            query = query.where(col(self.table.kind) == kind)
        if status is not None:
            query = query.where(col(self.table.status) == status)
        if is_read is not None:
            query = query.where(col(self.table.is_read) == is_read)
        if customer_id is not None:
            query = query.where(col(self.table.customer_id) == customer_id)
        result = await fetch_page(
            self.uow,
            query.order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result

    async def customer_page(
        self,
        customer_id: int,
        q: str | None,
        kind: str | None,
        is_read: bool | None,
        offset: int,
        limit: int,
    ) -> PagedType[NotificationModel]:
        query = select(self.table).where(
            col(self.table.customer_id) == customer_id,
            col(self.table.inbox_visible).is_(True),
        )
        if q:
            query = query.where(col(self.table.title).like(f"%{q}%"))
        if kind is not None:
            query = query.where(col(self.table.kind) == kind)
        if is_read is not None:
            query = query.where(col(self.table.is_read) == is_read)
        result = await fetch_page(
            self.uow,
            query.order_by(col(self.table.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result


class NotificationAttemptRepository(
    MySQLPersistenceRepository[NotificationAttemptModel]
):
    table = NotificationAttemptTable

    async def update_existing(
        self, row: NotificationAttemptModel, changes: NotificationAttemptModel
    ) -> NotificationAttemptModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def by_claim(
        self, notification_id: int, token: str
    ) -> NotificationAttemptModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.notification_id) == notification_id,
                col(self.table.claim_token) == token,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def page(
        self, notification_id: int, offset: int, limit: int
    ) -> PagedType[NotificationAttemptModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.notification_id) == notification_id)
            .order_by(col(self.table.attempt).desc()),
            offset=offset,
            limit=limit,
        )
        return result


class NotificationRecoveryRepository(
    MySQLPersistenceRepository[NotificationRecoveryModel]
):
    table = NotificationRecoveryTable

    async def page(
        self, notification_id: int, offset: int, limit: int
    ) -> PagedType[NotificationRecoveryModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.notification_id) == notification_id)
            .order_by(col(self.table.revision).desc()),
            offset=offset,
            limit=limit,
        )
        return result
