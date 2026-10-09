from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.node_capabilities.domain.models import (
    NodeCapabilityObservationModel,
)
from src.modules.network.node_capabilities.infra.tables import (
    NodeCapabilityObservationTable,
)


class NodeCapabilityObservationRepository(
    MySQLPersistenceRepository[NodeCapabilityObservationModel]
):
    table = NodeCapabilityObservationTable

    async def by_report(
        self, node_id: int, report_id: str
    ) -> NodeCapabilityObservationModel | None:
        result = await self.uow.execute(
            select(NodeCapabilityObservationTable)
            .where(
                col(NodeCapabilityObservationTable.node_id) == node_id,
                col(NodeCapabilityObservationTable.report_id) == report_id,
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
