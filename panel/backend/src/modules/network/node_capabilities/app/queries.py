import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal

from src.config.pagination import ServicePage
from src.modules.network.node_capabilities.app.observations import (
    NodeCapabilityPresentation,
)
from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityCapacity,
    NodeCapabilitySearch,
)
from src.modules.network.node_capabilities.domain.results import (
    NodeCapabilityLatest,
    NodeCapabilityObservation,
)
from src.modules.network.node_capabilities.infra.readers import (
    NodeCapabilityObservationReader,
)
from src.modules.network.nodes.interfaces import INodeService


class NodeCapabilityQuery:
    def __init__(
        self,
        nodes: INodeService,
        reader: NodeCapabilityObservationReader,
        capacity: NodeCapabilityCapacity,
    ) -> None:
        self.nodes, self.reader, self.capacity = nodes, reader, capacity

    async def latest(self, node_id: int) -> NodeCapabilityLatest:
        node = await self.nodes.get(node_id)
        row = await self.reader.latest(node_id)
        if row is None:
            return NodeCapabilityLatest(
                node_id=node_id, status="absent", observation=None
            )
        snapshot = NodeCapabilityPresentation.snapshot(row)
        observation = await asyncio.to_thread(
            NodeCapabilityPresentation.observation, snapshot, node.code
        )
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=self.capacity.freshness_seconds)
        status: Literal["fresh", "stale", "future"] = "fresh"
        if observation.observed_at > now + timedelta(
            seconds=self.capacity.future_skew_seconds
        ):
            status = "future"
        elif (
            observation.observed_at < cutoff
            or observation.received_at < cutoff
        ):
            status = "stale"
        return NodeCapabilityLatest(
            node_id=node_id, status=status, observation=observation
        )

    async def history(
        self, node_id: int, data: NodeCapabilitySearch
    ) -> ServicePage[NodeCapabilityObservation]:
        node = await self.nodes.get(node_id)
        limit = min(
            data.per_page or self.capacity.page_size,
            self.capacity.max_page_size,
        )
        rows = await self.reader.page(node_id, (data.page - 1) * limit, limit)
        snapshots = tuple(
            NodeCapabilityPresentation.snapshot(row) for row in rows.items
        )
        items = await asyncio.to_thread(
            NodeCapabilityPresentation.observations, snapshots, node.code
        )
        return ServicePage(
            items=items, total_items=rows.total_items, per_page=limit
        )
