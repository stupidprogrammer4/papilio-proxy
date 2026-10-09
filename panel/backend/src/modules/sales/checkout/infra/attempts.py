from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlmodel import col

from src.modules.sales.checkout.domain.attempts import CheckoutAttemptModel
from src.modules.sales.checkout.infra.tables import CheckoutAttemptTable


class CheckoutAttemptRepository(
    MySQLPersistenceRepository[CheckoutAttemptModel]
):
    table = CheckoutAttemptTable

    async def reserve(
        self, initial: CheckoutAttemptModel
    ) -> CheckoutAttemptModel:
        statement = insert(self.table).values(
            **initial.model_dump(exclude_unset=True)
        )
        # Unique-record admission happens before any missing-key locking read.
        # The competing create/retire operation waits on this actual record.
        await self.uow.execute(
            statement.on_duplicate_key_update(
                request_key=statement.inserted.request_key,
            )
        )
        rows = await self.uow.execute(
            select(self.table)
            .where(col(self.table.request_key) == initial.request_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return rows.scalar_one()

    async def change_existing(
        self, row: CheckoutAttemptModel, changes: CheckoutAttemptModel
    ) -> CheckoutAttemptModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row
