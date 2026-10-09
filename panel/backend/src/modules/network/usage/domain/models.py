from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TimestampField,
)


class UsageGrantModel(PersistenceEntity):
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", index=True)
    profile_id: int = ForeignKeyField("tbl_profiles.id", index=True)
    node_id: int = ForeignKeyField("tbl_nodes.id", index=True)
    generation: int = IntField()
    configuration_revision: int = IntField()
    request_key: str = CharField(128)
    mode: str = CharField(16)
    allocated_bytes: int = BigIntField()
    upload_bytes: int = BigIntField(default=0)
    download_bytes: int = BigIntField(default=0)
    sequence: int = IntField(default=0)
    is_closed: bool = BoolField(default=False)
    sampled_at: datetime | None = TimestampField(default=None)
    valid_until: datetime = TimestampField(index=True)
    installed_revision_id: int | None = ForeignKeyField(
        "tbl_core_runtime_revisions.id", default=None
    )
    usage_sha256: str | None = CharField(64, default=None)
    process_epoch: str | None = CharField(128, default=None)


class UsageEventModel(PersistenceEntity):
    grant_id: int = ForeignKeyField("tbl_usage_grants.id", index=True)
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", index=True)
    node_id: int = ForeignKeyField("tbl_nodes.id", index=True)
    generation: int = IntField()
    event_id: str = CharField(128)
    payload_hash: str = CharField(64)
    sequence: int = IntField()
    upload_bytes: int = BigIntField()
    download_bytes: int = BigIntField()
    delta_bytes: int = BigIntField()
    delta_upload_bytes: int = BigIntField()
    delta_download_bytes: int = BigIntField()
    final: bool = BoolField()
    sampled_at: datetime = TimestampField(index=True)
