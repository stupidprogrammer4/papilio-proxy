from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityReport,
)
from src.modules.network.node_capabilities.domain.models import (
    NodeCapabilityObservationModel,
)
from src.modules.network.node_capabilities.domain.results import (
    NodeCapabilityObservation,
    NodeCapabilityReceipt,
    NodeCapabilitySnapshot,
)


class NodeCapabilityPresentation:
    @staticmethod
    def snapshot(
        row: NodeCapabilityObservationModel,
    ) -> NodeCapabilitySnapshot:
        return NodeCapabilitySnapshot(
            row.id,
            row.node_id,
            row.report_id,
            row.report_sha256,
            row.normalized_report,
            row.observed_at,
            row.received_at,
        )

    @staticmethod
    def receipt(
        row: NodeCapabilityObservationModel, node_code: str
    ) -> NodeCapabilityReceipt:
        return NodeCapabilityReceipt(
            observation_id=row.id,
            node_id=row.node_id,
            node_code=node_code,
            report_id=row.report_id,
            report_sha256=row.report_sha256,
            observed_at=row.observed_at,
            received_at=row.received_at,
        )

    @staticmethod
    def parse(source: str) -> NodeCapabilityReport:
        return NodeCapabilityReport.model_validate_json(source)

    @classmethod
    def observation(
        cls, row: NodeCapabilitySnapshot, node_code: str
    ) -> NodeCapabilityObservation:
        return NodeCapabilityObservation(
            observation_id=row.observation_id,
            node_id=row.node_id,
            node_code=node_code,
            report_id=row.report_id,
            report_sha256=row.report_sha256,
            observed_at=row.observed_at,
            received_at=row.received_at,
            report=cls.parse(row.normalized_report),
        )

    @classmethod
    def observations(
        cls, rows: tuple[NodeCapabilitySnapshot, ...], node_code: str
    ) -> list[NodeCapabilityObservation]:
        return [
            NodeCapabilityObservation(
                observation_id=row.observation_id,
                node_id=row.node_id,
                node_code=node_code,
                report_id=row.report_id,
                report_sha256=row.report_sha256,
                observed_at=row.observed_at,
                received_at=row.received_at,
                report=cls.parse(row.normalized_report),
            )
            for row in rows
        ]
