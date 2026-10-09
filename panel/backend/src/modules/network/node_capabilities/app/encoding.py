import hashlib
import json
from dataclasses import dataclass

from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityReport,
)


@dataclass(frozen=True, slots=True)
class EncodedCapabilityReport:
    source: str
    sha256: str
    byte_count: int


class NodeCapabilityEncoding:
    @staticmethod
    def encode(report: NodeCapabilityReport) -> EncodedCapabilityReport:
        value = report.model_dump(mode="json")
        value["observed_at"] = report.observed_at.strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        source = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        payload = source.encode("utf-8")
        return EncodedCapabilityReport(
            source, hashlib.sha256(payload).hexdigest(), len(payload)
        )
