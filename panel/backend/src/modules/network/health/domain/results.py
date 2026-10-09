from dataclasses import dataclass
from datetime import datetime

from src.modules.network.health.domain.models import NodeHealthModel
from src.modules.network.nodes.domain.models import NodeModel


@dataclass(frozen=True, slots=True)
class ProbeHealthFacts:
    last_sample_at: datetime | None
    sample_count: int
    successful_count: int
    latency_total_ms: int


@dataclass(frozen=True, slots=True)
class NodeHealthFacts:
    health: NodeHealthModel
    node: NodeModel
