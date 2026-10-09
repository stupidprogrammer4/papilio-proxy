from papilio.infra.db.table import BaseTable

from src.modules.network.health.domain.models import NodeHealthModel


class NodeHealthTable(NodeHealthModel, BaseTable, table=True):
    table_name = "tbl_node_health"
