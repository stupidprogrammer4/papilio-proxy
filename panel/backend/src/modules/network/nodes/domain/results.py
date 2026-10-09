from dataclasses import dataclass

from src.modules.network.nodes.domain.models import NodeModel


@dataclass(frozen=True, slots=True)
class RegisteredNode:
    node: NodeModel
    agent_key: str


@dataclass(frozen=True, slots=True)
class NodeQuality:
    node_id: int
    code: str
    label: str
    protocol: str
    client_network: str
    sample_count: int
    successful_count: int
    average_latency_ms: int | None
    score: float | None


@dataclass(frozen=True, slots=True)
class NodeQualityFacts:
    node_id: int
    code: str
    label: str
    protocol: str
    sample_count: int
    successful_count: int
    latency_total_ms: int
