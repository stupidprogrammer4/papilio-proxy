from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.network.node_capabilities.domain.models import (
    NodeCapabilityObservationModel,
)
from src.modules.network.node_capabilities.infra.tables import (
    NodeCapabilityObservationTable,
)


class NodeCapabilityObservationReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def count(self, node_id: int) -> int:
        result = await self.uow.execute(
            select(func.count())
            .select_from(NodeCapabilityObservationTable)
            .where(col(NodeCapabilityObservationTable.node_id) == node_id)
        )
        return result.scalar_one()

    async def latest(
        self, node_id: int
    ) -> NodeCapabilityObservationModel | None:
        result = await self.uow.execute(
            select(NodeCapabilityObservationTable)
            .where(col(NodeCapabilityObservationTable.node_id) == node_id)
            .order_by(
                col(NodeCapabilityObservationTable.observed_at).desc(),
                col(NodeCapabilityObservationTable.received_at).desc(),
                col(NodeCapabilityObservationTable.id).desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def page(
        self, node_id: int, offset: int, limit: int
    ) -> PagedType[NodeCapabilityObservationModel]:
        statement = (
            select(NodeCapabilityObservationTable)
            .where(col(NodeCapabilityObservationTable.node_id) == node_id)
            .order_by(col(NodeCapabilityObservationTable.id).desc())
        )
        result = await fetch_page(
            self.uow, statement, offset=offset, limit=limit
        )
        return result
