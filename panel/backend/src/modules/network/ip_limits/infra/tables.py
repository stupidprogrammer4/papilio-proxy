from papilio.infra.db.table import BaseTable
from sqlalchemy import Index, UniqueConstraint

from src.modules.network.ip_limits.domain.models import (
    IpLeaseStateModel,
    IpLimitPolicyModel,
    IpSessionModel,
    PurchasedIpPolicyModel,
)


class IpLimitPolicyTable(IpLimitPolicyModel, BaseTable, table=True):
    table_name = "tbl_ip_limit_policies"


class PurchasedIpPolicyTable(PurchasedIpPolicyModel, BaseTable, table=True):
    pass


class IpLeaseStateTable(IpLeaseStateModel, BaseTable, table=True):
    pass


class IpSessionTable(IpSessionModel, BaseTable, table=True):
    table_name = "tbl_ip_sessions"
    __table_args__ = (
        UniqueConstraint("subscription_id", "source_ip", name="uq_ip_session"),
        Index("ix_ip_session_activity", "subscription_id", "expires_at"),
        Index("ix_ip_session_block", "subscription_id", "blocked_until"),
    )
