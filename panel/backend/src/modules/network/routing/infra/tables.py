from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.network.routing.domain.models import (
    HostGroupModel,
    HostMembershipModel,
    HostModel,
)


class HostTable(HostModel, BaseTable, table=True):
    pass


class HostGroupTable(HostGroupModel, BaseTable, table=True):
    pass


class HostMembershipTable(HostMembershipModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint("group_id", "host_id", name="uq_group_host"),
    )
