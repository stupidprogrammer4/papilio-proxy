from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.ip_limits.domain.models import IpLeaseStateModel
from src.modules.network.ip_limits.infra.tables import IpLeaseStateTable


class IpLeaseStateRepository(MySQLPersistenceRepository[IpLeaseStateModel]):
    table = IpLeaseStateTable

    async def locked(self, subscription_id: int) -> IpLeaseStateModel | None:
        result = await self.uow.execute(
            select(IpLeaseStateTable)
            .where(col(IpLeaseStateTable.subscription_id) == subscription_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def change(
        self, existing: IpLeaseStateModel, data: IpLeaseStateModel
    ) -> IpLeaseStateModel:
        await self.update_row_by_id(existing.id, data)
        await self.uow.refresh(existing)
        return existing
