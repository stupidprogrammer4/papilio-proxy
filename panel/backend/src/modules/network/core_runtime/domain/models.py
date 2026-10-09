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


class CoreRuntimeStateModel(PersistenceEntity):
    core_id: int = ForeignKeyField("tbl_cores.id", unique=True)
    revision: int = IntField(default=1)
    desired_revision_id: int | None = ForeignKeyField(
        "tbl_core_runtime_revisions.id", default=None
    )
    applied_revision_id: int | None = ForeignKeyField(
        "tbl_core_runtime_revisions.id", default=None
    )
    validated_revision_id: int | None = ForeignKeyField(
        "tbl_core_runtime_revisions.id", default=None
    )
    observed_status: str = CharField(16, default="unknown")
    automation_paused: bool = BoolField(default=False)
    last_observed_at: datetime | None = TimestampField(default=None)
    last_provision_scan_at: datetime | None = TimestampField(default=None)
    observed_process_epoch: str | None = CharField(128, default=None)


class CoreRuntimeRevisionModel(PersistenceEntity):
    core_id: int = ForeignKeyField("tbl_cores.id", index=True)
    created_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )
    mode: str = CharField(16)
    bundle_sha256: str = CharField(64)
    snapshot_sha256: str = CharField(64)
    entitlement_sha256: str = CharField(64)
    artifact_count: int = IntField()
    encrypted_payload: str = TextField()
    encrypted_memberships: str | None = TextField(default=None)
    membership_sha256: str | None = CharField(64, default=None)
    encrypted_usage: str | None = TextField(default=None)
    usage_sha256: str | None = CharField(64, default=None)


class CoreRuntimeCommandModel(PersistenceEntity):
    core_id: int = ForeignKeyField("tbl_cores.id", index=True)
    node_id: int = ForeignKeyField("tbl_nodes.id", index=True)
    purpose: str = CharField(16, default="operator")
    action: str = CharField(16)
    reconcile_mode: str | None = CharField(16, default=None)
    revision_id: int | None = ForeignKeyField(
        "tbl_core_runtime_revisions.id", default=None
    )
    state: str = CharField(16, default="queued", index=True)
    created_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )
    request_key: str = CharField(128)
    request_sha256: str = CharField(64)
    reason: str = CharField(250)
    available_at: datetime = TimestampField()
    attempts: int = IntField(default=0)
    claim_hash: str | None = CharField(64, default=None)
    claim_until: datetime | None = TimestampField(default=None)
    ack_sha256: str | None = CharField(64, default=None)
    error_code: str | None = CharField(64, default=None)
