from datetime import datetime

from papilio.infra.db.table import BaseTable
from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, LONGTEXT
from sqlmodel import Field

from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedBarrierModel,
    ManagedEpochModel,
    ManagedInstallationModel,
    ManagedOperationBatchModel,
    ManagedRevocationModel,
    ManagedWindowModel,
)


class ManagedInstallationTable(
    ManagedInstallationModel, BaseTable, table=True
):
    encrypted_manifest: str = Field(sa_type=LONGTEXT)
    claim_until: datetime | None = Field(
        default=None, sa_column=Column(DATETIME(fsp=6), nullable=True)
    )
    __table_args__ = (
        UniqueConstraint(
            "core_id",
            "runtime_revision_id",
            "installation_sha256",
            name="uq_managed_installation_identity",
        ),
    )


class ManagedEpochTable(ManagedEpochModel, BaseTable, table=True):
    encrypted_receipt: str = Field(sa_type=LONGTEXT)
    installed_closed_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    __table_args__ = (
        UniqueConstraint("process_epoch", name="uq_managed_process_epoch"),
        UniqueConstraint(
            "installation_id",
            "process_epoch",
            name="uq_managed_epoch_identity",
        ),
        UniqueConstraint(
            "previous_epoch_id", name="uq_managed_epoch_successor"
        ),
        UniqueConstraint(
            "rollover_request_id", name="uq_managed_epoch_rollover_request"
        ),
    )


class ManagedOperationBatchTable(
    ManagedOperationBatchModel, BaseTable, table=True
):
    accepted_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "operation",
            "request_key",
            name="uq_managed_operation_batch_request",
        ),
    )


class ManagedBarrierTable(ManagedBarrierModel, BaseTable, table=True):
    frozen_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    accepted_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    encrypted_receipt: str = Field(sa_type=LONGTEXT)
    __table_args__ = (
        UniqueConstraint(
            "epoch_id", "barrier_id", name="uq_managed_barrier_identity"
        ),
        UniqueConstraint(
            "acceptance_id", name="uq_managed_barrier_acceptance"
        ),
    )


class ManagedWindowTable(ManagedWindowModel, BaseTable, table=True):
    issued_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    valid_until: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    encrypted_window: str = Field(sa_type=LONGTEXT)
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "generation",
            "request_key",
            name="uq_managed_window_request",
        ),
    )


class ManagedAdmissionTable(ManagedAdmissionModel, BaseTable, table=True):
    encrypted_receipt: str = Field(sa_type=LONGTEXT)


class ManagedRevocationTable(ManagedRevocationModel, BaseTable, table=True):
    encrypted_receipt: str = Field(sa_type=LONGTEXT)
    observed_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
