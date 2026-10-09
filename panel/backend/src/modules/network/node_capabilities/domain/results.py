from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityReport,
)


class NodeCapabilityReceipt(BaseModel):
    observation_id: int
    node_id: int
    node_code: str
    report_id: str
    report_sha256: str
    observed_at: datetime
    received_at: datetime

    @field_validator("observed_at", "received_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )


class NodeCapabilityObservation(NodeCapabilityReceipt):
    evidence_kind: Literal["authenticated_node_self_report"] = (
        "authenticated_node_self_report"
    )
    report: NodeCapabilityReport


class NodeCapabilityLatest(BaseModel):
    node_id: int
    status: Literal["absent", "fresh", "stale", "future"]
    observation: NodeCapabilityObservation | None


@dataclass(frozen=True, slots=True)
class NodeCapabilitySnapshot:
    observation_id: int
    node_id: int
    report_id: str
    report_sha256: str
    normalized_report: str
    observed_at: datetime
    received_at: datetime
