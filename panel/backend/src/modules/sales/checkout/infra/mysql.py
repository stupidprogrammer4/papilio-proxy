from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import or_, select
from sqlmodel import col

from src.modules.sales.checkout.domain.attempts import CheckoutIntentIdentity
from src.modules.sales.checkout.domain.models import (
    CheckoutActionReceiptModel,
    CheckoutIntentModel,
)
from src.modules.sales.checkout.infra.tables import (
    CheckoutActionReceiptTable,
    CheckoutIntentTable,
)


class CheckoutIntentRepository(
    MySQLPersistenceRepository[CheckoutIntentModel]
):
    table = CheckoutIntentTable

    async def identity(self, id: int) -> CheckoutIntentIdentity | None:
        result = await self.uow.execute(
            select(
                col(self.table.customer_id), col(self.table.request_key)
            ).where(col(self.table.id) == id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return CheckoutIntentIdentity(
            customer_id=row.customer_id, request_key=row.request_key
        )

    async def update_existing(
        self, existing: CheckoutIntentModel, changes: CheckoutIntentModel
    ) -> CheckoutIntentModel:
        await self.update_row_by_id(existing.id, changes)
        await self.uow.refresh(existing)
        return existing

    async def owned_current(
        self, id: int, customer_id: int
    ) -> CheckoutIntentModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.id) == id,
                col(self.table.customer_id) == customer_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def locked(self, id: int) -> CheckoutIntentModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def by_request_key_current(
        self, key: str
    ) -> CheckoutIntentModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.request_key) == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def page_owned(
        self, customer_id: int, state: str | None, offset: int, limit: int
    ) -> PagedType[CheckoutIntentModel]:
        query = (
            select(self.table)
            .where(col(self.table.customer_id) == customer_id)
            .order_by(col(self.table.id).desc())
        )
        if state is not None:
            query = query.where(col(self.table.state) == state)
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result

    async def by_topup(self, topup_id: int) -> CheckoutIntentModel | None:
        result = await self.uow.execute(
            select(self.table).where(col(self.table.topup_id) == topup_id)
        )
        return result.scalar_one_or_none()

    async def due_ids(
        self, states: list[str], before: datetime, limit: int
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(self.table.id))
            .where(
                col(self.table.state).in_(states),
                or_(
                    col(self.table.checked_at).is_(None),
                    col(self.table.checked_at) <= before,
                ),
            )
            .order_by(col(self.table.checked_at), col(self.table.id))
            .limit(limit)
        )
        return list(result.scalars().all())


class CheckoutActionReceiptRepository(
    MySQLPersistenceRepository[CheckoutActionReceiptModel]
):
    table = CheckoutActionReceiptTable

    async def by_key_current(
        self, key: str
    ) -> CheckoutActionReceiptModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.request_key) == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
