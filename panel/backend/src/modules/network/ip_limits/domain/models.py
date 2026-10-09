from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)


class IpLimitPolicyModel(PersistenceEntity):
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", unique=True)
    enabled: bool = BoolField()
    max_ips: int = IntField()
    lease_seconds: int = IntField()
    ban_seconds: int = IntField()
    mode: str = CharField(32)


class PurchasedIpPolicyModel(PersistenceEntity):
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", unique=True)
    plan_id: int | None = ForeignKeyField("tbl_plans.id", default=None)
    source: str = CharField(32)
    policy_json: str = TextField()


class IpSessionModel(PersistenceEntity):
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", index=True)
    source_ip: str = CharField(45)
    last_node_id: int = ForeignKeyField("tbl_nodes.id")
    first_seen_at: datetime = TimestampField()
    last_seen_at: datetime = TimestampField()
    expires_at: datetime = TimestampField()
    blocked_until: datetime | None = TimestampField(default=None)
    block_reason: str | None = CharField(250, default=None)
    blocked_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )


class IpLeaseStateModel(PersistenceEntity):
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", unique=True)
    history_complete: bool = BoolField()
    issued_until: datetime | None = TimestampField(default=None)
    pending_policy_json: str | None = TextField(default=None)
    previous_policy_json: str | None = TextField(default=None)
    previous_source: str | None = CharField(32, default=None)
    transition_mode: str | None = CharField(32, default=None)
    drain_until: datetime | None = TimestampField(default=None)
    blocked_reason: str | None = CharField(64, default=None)
