from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.network.balancing.domain.models import BalancerPolicyModel


class BalancerPolicyTable(BalancerPolicyModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint(
            "group_id", "client_core", name="uq_balancer_group_core"
        ),
    )
