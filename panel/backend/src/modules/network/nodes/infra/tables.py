from papilio.infra.db.table import BaseTable
from sqlalchemy import Index

from src.modules.network.nodes.domain.models import NodeModel, ProbeModel


class NodeTable(NodeModel, BaseTable, table=True):
    pass


class ProbeTable(ProbeModel, BaseTable, table=True):
    __table_args__ = (
        Index("ix_probe_node_time", "node_id", "sampled_at"),
        Index(
            "ix_probe_node_network_time",
            "node_id",
            "client_network",
            "sampled_at",
        ),
    )
