from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.health.domain.models import NodeHealthModel
from src.modules.network.health.infra.tables import NodeHealthTable


class NodeHealthRepository(MySQLPersistenceRepository[NodeHealthModel]):
    table = NodeHealthTable

    async def store(self, data: NodeHealthModel) -> NodeHealthModel:
        result = await self.uow.execute(
            select(NodeHealthTable).where(
                col(NodeHealthTable.node_id) == data.node_id
            )
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            created = await self.create(data)
            return created
        await self.update_row_by_id(stored.id, data)
        await self.uow.refresh(stored)
        return stored
