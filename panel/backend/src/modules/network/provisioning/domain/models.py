from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)


class ProvisionRequestModel(PersistenceEntity):
    completion: str = CharField(16, default="refund")
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", index=True)
    generation: int = IntField()
    policy_json: str = TextField()
    state: str = CharField(32, default="queued", index=True)
    reason_code: str | None = CharField(64, default=None)
    checked_at: datetime | None = TimestampField(default=None)
    deadline_at: datetime = TimestampField()
    retry_reason: str | None = CharField(250, default=None)
    activated_at: datetime | None = TimestampField(default=None)
    cancellation_reason: str | None = CharField(250, default=None)
    cancelled_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )


class ProvisionTaskModel(PersistenceEntity):
    configuration_revision: int = IntField()
    installed_revision_id: int | None = ForeignKeyField(
        "tbl_core_runtime_revisions.id", default=None
    )
    membership_sha256: str | None = CharField(64, default=None)
    ack_sha256: str | None = CharField(64, default=None)
    encrypted_payload: str = TextField()
    request_id: int = ForeignKeyField("tbl_provision_requests.id", index=True)
    configuration_id: int = ForeignKeyField("tbl_configurations.id")
    profile_id: int = ForeignKeyField("tbl_profiles.id")
    node_id: int = ForeignKeyField("tbl_nodes.id", index=True)
    action: str = CharField(16, default="apply")
    state: str = CharField(32, default="queued", index=True)
    attempts: int = IntField(default=0)
    claim_hash: str | None = CharField(64, default=None)
    claim_until: datetime | None = TimestampField(default=None)
    acknowledged_at: datetime | None = TimestampField(default=None)
    last_outcome: str | None = CharField(16, default=None)
    error_code: str | None = CharField(64, default=None)
    available_at: datetime = TimestampField(index=True)
