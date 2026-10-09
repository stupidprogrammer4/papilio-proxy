from papilio.infra.db.table import BaseTable
from sqlalchemy import Index, UniqueConstraint

from src.modules.network.usage.domain.models import (
    UsageEventModel,
    UsageGrantModel,
)


class UsageGrantTable(UsageGrantModel, BaseTable, table=True):
    __table_args__ = (
        Index(
            "ix_usage_reservations",
            "subscription_id",
            "generation",
            "is_closed",
            "mode",
        ),
        Index(
            "ix_usage_profile_open", "profile_id", "generation", "is_closed"
        ),
        UniqueConstraint(
            "profile_id",
            "generation",
            "request_key",
            name="uq_usage_allocation",
        ),
    )


class UsageEventTable(UsageEventModel, BaseTable, table=True):
    __table_args__ = (
        Index("ix_usage_subscription_time", "subscription_id", "sampled_at"),
        Index("ix_usage_node_time", "node_id", "sampled_at"),
        UniqueConstraint("node_id", "event_id", name="uq_usage_event"),
    )
