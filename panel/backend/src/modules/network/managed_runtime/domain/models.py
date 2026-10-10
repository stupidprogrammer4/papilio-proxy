"""Immutable authority facts; no row here marks a profile active."""

from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)


class ManagedInstallationModel(PersistenceEntity):
    node_id: int = ForeignKeyField("tbl_nodes.id")
    core_id: int = ForeignKeyField("tbl_cores.id")
    runtime_revision_id: int = ForeignKeyField("tbl_core_runtime_revisions.id")
    installation_sha256: str = CharField(64)
    encrypted_manifest: str = TextField()
    state: str = CharField(16, default="issued")
    claim_hash: str | None = CharField(64, default=None)
    claim_until: datetime | None = TimestampField(default=None)
    acknowledgement_sha256: str | None = CharField(64, default=None)


class ManagedEpochModel(PersistenceEntity):
    installation_id: int = ForeignKeyField("tbl_managed_installations.id")
    process_epoch: str = CharField(32)
    installed_closed_at: datetime = TimestampField()
    receipt_sha256: str = CharField(64)
    encrypted_receipt: str = TextField()


class ManagedBarrierModel(PersistenceEntity):
    epoch_id: int = ForeignKeyField("tbl_managed_epoches.id")
    barrier_id: str = CharField(32)
    acceptance_id: str = CharField(32)
    snapshot_sha256: str = CharField(64)
    request_sha256: str = CharField(64)
    frozen_at: datetime = TimestampField()
    accepted_at: datetime = TimestampField()
    encrypted_receipt: str = TextField()


class ManagedWindowModel(PersistenceEntity):
    encrypted_provision_claim: str | None = TextField(default=None)
    epoch_id: int = ForeignKeyField("tbl_managed_epoches.id")
    grant_id: int = ForeignKeyField("tbl_usage_grants.id", unique=True)
    profile_id: int = ForeignKeyField("tbl_profiles.id")
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id")
    provision_task_id: int | None = ForeignKeyField(
        "tbl_provision_tasks.id", default=None
    )
    generation: int = IntField()
    window_id: str = CharField(32, unique=True)
    request_key: str = CharField(128)
    request_sha256: str = CharField(64)
    window_sha256: str = CharField(64)
    baseline_upload_bytes: int = BigIntField()
    baseline_download_bytes: int = BigIntField()
    allocated_bytes: int = BigIntField()
    issued_at: datetime = TimestampField()
    valid_until: datetime = TimestampField()
    predecessor_id: int | None = ForeignKeyField(
        "tbl_managed_barriers.id", default=None
    )
    encrypted_window: str = TextField()


class ManagedAdmissionModel(PersistenceEntity):
    window_id: int = ForeignKeyField("tbl_managed_windows.id", unique=True)
    provision_task_id: int = ForeignKeyField("tbl_provision_tasks.id")
    receipt_sha256: str = CharField(64)
    outcome: str = CharField(16)
    observed_at: datetime = TimestampField()
    encrypted_receipt: str = TextField()


class ManagedRevocationModel(PersistenceEntity):
    window_id: int = ForeignKeyField("tbl_managed_windows.id", unique=True)
    provision_task_id: int = ForeignKeyField("tbl_provision_tasks.id")
    receipt_sha256: str = CharField(64)
    observed_at: datetime = TimestampField()
    encrypted_receipt: str = TextField()
