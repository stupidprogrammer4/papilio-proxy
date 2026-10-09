from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import case, func, or_, select
from sqlmodel import col

from src.modules.network.health.domain.results import (
    NodeHealthFacts,
    ProbeHealthFacts,
)
from src.modules.network.health.infra.tables import NodeHealthTable
from src.modules.network.nodes.infra.tables import NodeTable, ProbeTable


class NodeHealthReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def due_ids(self, before: datetime, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(NodeTable.id))
            .outerjoin(
                NodeHealthTable,
                col(NodeHealthTable.node_id) == col(NodeTable.id),
            )
            .where(
                or_(
                    col(NodeHealthTable.checked_at).is_(None),
                    col(NodeHealthTable.checked_at) <= before,
                )
            )
            .order_by(col(NodeHealthTable.checked_at), col(NodeTable.id))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def probes(
        self, node_id: int, since: datetime, until: datetime
    ) -> ProbeHealthFacts:
        latest = await self.uow.execute(
            select(func.max(col(ProbeTable.sampled_at))).where(
                col(ProbeTable.node_id) == node_id,
                col(ProbeTable.sampled_at) <= until,
            )
        )
        successful = col(ProbeTable.success).is_(True)
        result = await self.uow.execute(
            select(
                func.count(col(ProbeTable.id)).label("sample_count"),
                func.coalesce(
                    func.sum(case((successful, 1), else_=0)), 0
                ).label("successful_count"),
                func.coalesce(
                    func.sum(
                        case((successful, col(ProbeTable.latency_ms)), else_=0)
                    ),
                    0,
                ).label("latency_total_ms"),
            ).where(
                col(ProbeTable.node_id) == node_id,
                col(ProbeTable.sampled_at) >= since,
                col(ProbeTable.sampled_at) <= until,
            )
        )
        return ProbeHealthFacts(
            last_sample_at=latest.scalar_one(), **result.mappings().one()
        )

    async def page(
        self,
        status: str | None,
        node_id: int | None,
        q: str | None,
        offset: int,
        limit: int,
    ) -> PagedType[NodeHealthFacts]:
        query = select(NodeHealthTable, NodeTable).join(
            NodeTable, col(NodeTable.id) == col(NodeHealthTable.node_id)
        )
        if status is not None:
            query = query.where(col(NodeHealthTable.status) == status)
        if node_id is not None:
            query = query.where(col(NodeTable.id) == node_id)
        if q:
            query = query.where(
                or_(
                    col(NodeTable.label).contains(q, autoescape=True),
                    col(NodeTable.code).contains(q, autoescape=True),
                )
            )
        count = await self.uow.execute(
            select(func.count()).select_from(query.subquery())
        )
        result = await self.uow.execute(
            query.order_by(
                col(NodeHealthTable.checked_at).desc(),
                col(NodeHealthTable.id).desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return PagedType(
            items=[
                NodeHealthFacts(row.NodeHealthTable, row.NodeTable)
                for row in result
            ],
            total_items=count.scalar_one(),
        )
