from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.network.health.domain.models import NodeHealthModel
from src.modules.network.health.infra.mysql import NodeHealthRepository
from src.modules.network.health.infra.readers import NodeHealthReader
from src.modules.network.nodes.infra.mysql import NodeRepository
from src.modules.operations.preferences.interfaces import IPreferencesService


class NodeHealthCommand:
    def __init__(
        self,
        nodes: NodeRepository,
        health: NodeHealthRepository,
        reader: NodeHealthReader,
        settings: PapilioSettings,
        preferences: IPreferencesService,
    ) -> None:
        self.nodes = nodes
        self.health = health
        self.reader = reader
        self.settings = settings
        self.preferences = preferences

    @transactional
    async def check(self, node_id: int) -> NodeHealthModel:
        node = await self.nodes.locked(node_id)
        if node is None:
            raise NotFoundException(
                message="نود پیدا نشد.",
                message_code="node_not_found",
                entity="node",
                identifier="id",
                identifier_value=node_id,
            )
        now = datetime.now(UTC).replace(tzinfo=None)
        policy = self.settings.operations
        preferences = (await self.preferences.current()).values
        facts = await self.reader.probes(
            node_id,
            now - timedelta(minutes=policy.quality_window_minutes),
            now,
        )
        if not node.is_enabled:
            status = "disabled"
        elif facts.last_sample_at is None:
            status = "unknown"
        elif facts.last_sample_at <= now - timedelta(
            seconds=preferences.node_health_stale_seconds
        ):
            status = "stale"
        elif facts.sample_count < policy.quality_min_samples:
            status = "insufficient"
        elif facts.successful_count == 0:
            status = "unreachable"
        elif (
            facts.successful_count / facts.sample_count
            < policy.quality_min_success_ratio
        ):
            status = "degraded"
        else:
            status = "healthy"
        result = await self.health.store(
            NodeHealthModel(
                node_id=node_id,
                status=status,
                sample_count=facts.sample_count,
                successful_count=facts.successful_count,
                average_latency_ms=round(
                    facts.latency_total_ms / facts.successful_count
                )
                if facts.successful_count
                else None,
                last_sample_at=facts.last_sample_at,
                checked_at=now,
            )
        )
        return result
