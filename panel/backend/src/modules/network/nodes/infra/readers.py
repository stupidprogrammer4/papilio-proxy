from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import case, func, select
from sqlmodel import col

from src.modules.network.nodes.domain.results import NodeQualityFacts
from src.modules.network.nodes.infra.tables import NodeTable, ProbeTable


class NodeQualityFactsReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def for_network(
        self,
        client_network: str,
        since: datetime,
        until: datetime,
        enabled: bool,
    ) -> list[NodeQualityFacts]:
        success = case((col(ProbeTable.success).is_(True), 1), else_=0)
        latency = case(
            (col(ProbeTable.success).is_(True), col(ProbeTable.latency_ms)),
            else_=0,
        )
        result = await self.uow.execute(
            select(
                col(NodeTable.id).label("node_id"),
                col(NodeTable.code),
                col(NodeTable.label),
                col(NodeTable.protocol),
                func.count(col(ProbeTable.id)).label("sample_count"),
                func.coalesce(func.sum(success), 0).label("successful_count"),
                func.coalesce(func.sum(latency), 0).label("latency_total_ms"),
            )
            .outerjoin(
                ProbeTable,
                (col(ProbeTable.node_id) == col(NodeTable.id))
                & (col(ProbeTable.client_network) == client_network)
                & (col(ProbeTable.sampled_at) >= since)
                & (col(ProbeTable.sampled_at) <= until),
            )
            .where(col(NodeTable.is_enabled).is_(enabled))
            .group_by(
                col(NodeTable.id),
                col(NodeTable.code),
                col(NodeTable.label),
                col(NodeTable.protocol),
            )
        )
        return [NodeQualityFacts(**row) for row in result.mappings().all()]
