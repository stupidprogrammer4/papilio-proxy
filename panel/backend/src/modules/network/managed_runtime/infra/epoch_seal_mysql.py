from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.managed_runtime.domain.epoch_seal_models import (
    ManagedEpochSealModel,
)
from src.modules.network.managed_runtime.infra.epoch_seal_tables import (
    ManagedEpochSealTable,
)


class ManagedEpochSealRepository(
    MySQLPersistenceRepository[ManagedEpochSealModel]
):
    table = ManagedEpochSealTable

    async def by_epoch(self, epoch_id: int) -> ManagedEpochSealModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.epoch_id) == epoch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
