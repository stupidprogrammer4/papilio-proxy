from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.balancing.domain.models import BalancerPolicyModel
from src.modules.network.balancing.infra.tables import BalancerPolicyTable


class BalancerPolicyRepository(
    MySQLPersistenceRepository[BalancerPolicyModel]
):
    table = BalancerPolicyTable

    async def for_group(
        self, group_id: int, client_core: str, locked: bool = False
    ) -> BalancerPolicyModel | None:
        statement = select(BalancerPolicyTable).where(
            col(BalancerPolicyTable.group_id) == group_id,
            col(BalancerPolicyTable.client_core) == client_core,
        )
        if locked:
            statement = statement.with_for_update()
        result = await self.uow.execute(statement)
        return result.scalar_one_or_none()

    async def change(
        self, row: BalancerPolicyModel, changes: BalancerPolicyModel
    ) -> BalancerPolicyModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row
