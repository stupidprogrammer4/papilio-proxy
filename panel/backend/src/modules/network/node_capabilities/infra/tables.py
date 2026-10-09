from papilio.infra.db.table import BaseTable
from sqlalchemy import Index, UniqueConstraint

from src.modules.network.node_capabilities.domain.models import (
    NodeCapabilityObservationModel,
)


class NodeCapabilityObservationTable(
    NodeCapabilityObservationModel, BaseTable, table=True
):
    __table_args__ = (
        UniqueConstraint(
            "node_id", "report_id", name="uq_capability_node_report"
        ),
        Index(
            "ix_capability_node_observed",
            "node_id",
            "observed_at",
            "received_at",
            "id",
        ),
    )
