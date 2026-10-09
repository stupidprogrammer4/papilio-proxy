from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.billing.destinations.domain.models import (
    PaymentDestinationModel,
)
from src.modules.billing.destinations.infra.tables import (
    PaymentDestinationTable,
)


class PaymentDestinationRepository(
    MySQLPersistenceRepository[PaymentDestinationModel]
):
    table = PaymentDestinationTable

    async def locked(self, id: int) -> PaymentDestinationModel | None:
        result = await self.uow.execute(
            select(PaymentDestinationTable)
            .where(col(PaymentDestinationTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: PaymentDestinationModel, changes: PaymentDestinationModel
    ) -> PaymentDestinationModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def page(
        self,
        q: str | None,
        active: bool | None,
        kinds: list[str] | None,
        offset: int,
        limit: int,
    ) -> PagedType[PaymentDestinationModel]:
        statement = select(PaymentDestinationTable).order_by(
            col(PaymentDestinationTable.id).desc()
        )
        if q:
            statement = statement.where(
                func.lower(col(PaymentDestinationTable.title)).like(
                    f"%{q.lower()}%"
                )
            )
        if active is not None:
            statement = statement.where(
                col(PaymentDestinationTable.is_active).is_(active)
            )
        if kinds is not None:
            statement = statement.where(
                col(PaymentDestinationTable.kind).in_(kinds)
            )
        result = await fetch_page(
            self.uow, statement, offset=offset, limit=limit
        )
        return result
