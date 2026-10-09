from datetime import datetime

from papilio.infra.db.table import BaseTable
from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlmodel import Field

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
    issued_until: datetime | None = Field(
        default=None, sa_column=Column(DATETIME(fsp=6), nullable=True)
    )
    drain_until: datetime | None = Field(
        default=None, sa_column=Column(DATETIME(fsp=6), nullable=True)
    )


class IpSessionTable(IpSessionModel, BaseTable, table=True):
    table_name = "tbl_ip_sessions"
    first_seen_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    last_seen_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    expires_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    blocked_until: datetime | None = Field(
        default=None, sa_column=Column(DATETIME(fsp=6), nullable=True)
    )
    __table_args__ = (
        UniqueConstraint("subscription_id", "source_ip", name="uq_ip_session"),
        Index("ix_ip_session_activity", "subscription_id", "expires_at"),
        Index("ix_ip_session_block", "subscription_id", "blocked_until"),
    )
