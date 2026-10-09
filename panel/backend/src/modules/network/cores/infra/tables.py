from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.network.cores.domain.models import CoreModel


class CoreTable(CoreModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint("node_id", "code", name="uq_core_node_code"),
    )
