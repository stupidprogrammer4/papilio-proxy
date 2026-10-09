from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import or_, select
from sqlmodel import col

from src.modules.network.nodes.domain.models import NodeModel, ProbeModel
from src.modules.network.nodes.infra.tables import NodeTable, ProbeTable


class NodeRepository(MySQLPersistenceRepository[NodeModel]):
    table = NodeTable

    async def locked(self, id: int) -> NodeModel | None:
        result = await self.uow.execute(
            select(NodeTable)
            .where(col(NodeTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def by_code(self, code: str) -> NodeModel | None:
        result = await self.uow.execute(
            select(NodeTable).where(col(NodeTable.code) == code)
        )
        return result.scalar_one_or_none()

    async def page(
        self, offset: int, limit: int, q: str | None
    ) -> PagedType[NodeModel]:
        query = select(NodeTable).order_by(col(NodeTable.id).desc())
        if q:
            escaped = (
                q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            query = query.where(
                or_(
                    col(NodeTable.label).like(pattern),
                    col(NodeTable.code).like(pattern),
                )
            )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result

    async def update_existing(
        self, node: NodeModel, enabled: bool
    ) -> NodeModel:
        await self.update_row_by_id(
            node.id, NodeModel.patch(is_enabled=enabled)
        )
        await self.uow.refresh(node)
        return node


class ProbeRepository(MySQLPersistenceRepository[ProbeModel]):
    table = ProbeTable

    async def by_event_id(self, event_id: str) -> ProbeModel | None:
        result = await self.uow.execute(
            select(ProbeTable).where(col(ProbeTable.event_id) == event_id)
        )
        return result.scalar_one_or_none()
