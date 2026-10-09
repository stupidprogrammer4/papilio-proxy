from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field

from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedBarrierModel,
    ManagedEpochModel,
    ManagedInstallationModel,
    ManagedWindowModel,
)


class ManagedInstallationTable(
    ManagedInstallationModel, BaseTable, table=True
):
    encrypted_manifest: str = Field(sa_type=LONGTEXT())
    __table_args__ = (
        UniqueConstraint(
            "core_id",
            "runtime_revision_id",
            "installation_sha256",
            name="uq_managed_installation_identity",
        ),
    )


class ManagedEpochTable(ManagedEpochModel, BaseTable, table=True):
    encrypted_receipt: str = Field(sa_type=LONGTEXT())
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "process_epoch",
            name="uq_managed_epoch_identity",
        ),
    )


class ManagedBarrierTable(ManagedBarrierModel, BaseTable, table=True):
    encrypted_receipt: str = Field(sa_type=LONGTEXT())
    __table_args__ = (
        UniqueConstraint(
            "epoch_id", "barrier_id", name="uq_managed_barrier_identity"
        ),
        UniqueConstraint(
            "acceptance_id", name="uq_managed_barrier_acceptance"
        ),
    )


class ManagedWindowTable(ManagedWindowModel, BaseTable, table=True):
    encrypted_window: str = Field(sa_type=LONGTEXT())
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "generation",
            "request_key",
            name="uq_managed_window_request",
        ),
    )


class ManagedAdmissionTable(ManagedAdmissionModel, BaseTable, table=True):
    encrypted_receipt: str = Field(sa_type=LONGTEXT())
