"""Managed authority contracts; local receipts are not API grants."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
EpochIdentity = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
ByteCount = Annotated[int, Field(ge=0, le=2**63 - 1)]


class ImmutableContract(BaseModel):
    model_config = ConfigDict(frozen=True)


class ManagedRuntimeCapacity(ImmutableContract):
    """Owning limits reserved for a future explicitly enabled adapter."""

    max_manifest_bytes: int = Field(gt=0)
    max_window_bytes: int = Field(gt=0)
    max_snapshot_bytes: int = Field(gt=0)
    max_profiles_per_barrier: int = Field(gt=0)
    max_windows_per_barrier: int = Field(gt=0)
    max_pending_epochs: int = Field(gt=0)
    max_retained_receipts: int = Field(gt=0)
    max_validity_ms: int = Field(gt=0)
    operation_timeout_ms: int = Field(gt=0)
    scan_batch_size: int = Field(gt=0)
    retry_seconds: int = Field(gt=0)
    max_attempts: int = Field(gt=0)


class ManagedInstallation(ImmutableContract):
    runtime_revision_id: int = Field(gt=0)
    membership_sha256: Sha256
    artifact_filename: str = Field(min_length=1)
    artifact_sha256: Sha256
    adapter_revision: int = Field(gt=0)
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    executable_sha256: Sha256
    original_document_sha256: Sha256
    document_sha256: Sha256
    materials_sha256: Sha256
    bindings_sha256: Sha256
    accounting_scope: Literal["decoded_managed_tcp_payload_admission"]
    budget_enforced: bool
    deadline_enforced: bool


class ManagedProfileBinding(ImmutableContract):
    profile_id: int = Field(gt=0)
    subscription_id: int = Field(gt=0)
    generation: int = Field(ge=0)
    configuration_id: int = Field(gt=0)
    configuration_revision: int = Field(gt=0)
    credential_sha256: Sha256
    profile_sha256: Sha256
    counter_identity: str = Field(min_length=1)
    inbound_tag: str = Field(min_length=1)


class ManagedPredecessor(ImmutableContract):
    acceptance_id: EpochIdentity
    epoch: EpochIdentity
    profile_id: int = Field(gt=0)
    barrier_id: EpochIdentity
    snapshot_sha256: Sha256


class ManagedWindow(ImmutableContract):
    grant_id: int = Field(gt=0)
    window_id: EpochIdentity
    epoch: EpochIdentity
    installation: ManagedInstallation
    binding: ManagedProfileBinding
    membership_sha256: Sha256
    baseline_upload_bytes: ByteCount
    baseline_download_bytes: ByteCount
    allocated_bytes: int = Field(gt=0, le=2**63 - 1)
    issued_at: datetime
    valid_until: datetime
    predecessor: ManagedPredecessor | None

    @model_validator(mode="after")
    def valid_window(self) -> "ManagedWindow":
        if self.issued_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("Managed window times require UTC offsets")
        if self.valid_until <= self.issued_at:
            raise ValueError("Managed window must have a positive validity")
        if (
            self.baseline_upload_bytes + self.baseline_download_bytes
            > 2**63 - 1
        ):
            raise ValueError("Managed baseline exceeds the counter protocol")
        if self.membership_sha256 != self.installation.membership_sha256:
            raise ValueError("Window membership must match its installation")
        if self.predecessor is not None and (
            self.predecessor.epoch != self.epoch
            or self.predecessor.profile_id != self.binding.profile_id
        ):
            raise ValueError("Window predecessor belongs to another binding")
        return self


class ManagedFinalCounters(ImmutableContract):
    window_id: EpochIdentity
    grant_id: int = Field(gt=0)
    profile_id: int = Field(gt=0)
    upload_bytes: ByteCount
    download_bytes: ByteCount

    @model_validator(mode="after")
    def valid_total(self) -> "ManagedFinalCounters":
        if self.upload_bytes + self.download_bytes > 2**63 - 1:
            raise ValueError("Managed totals exceed the counter protocol")
        return self


class ManagedBarrierSubmission(ImmutableContract):
    epoch: EpochIdentity
    barrier_id: EpochIdentity
    installation_sha256: Sha256
    snapshot_sha256: Sha256
    frozen_at: datetime
    windows: tuple[ManagedWindow, ...]
    totals: tuple[ManagedFinalCounters, ...]

    @model_validator(mode="after")
    def exact_window_set(self) -> "ManagedBarrierSubmission":
        if self.frozen_at.tzinfo is None:
            raise ValueError("Managed snapshot time requires its UTC offset")
        windows = {(row.window_id, row.grant_id) for row in self.windows}
        totals = {(row.window_id, row.grant_id) for row in self.totals}
        if not windows or len(windows) != len(self.windows):
            raise ValueError("Barrier windows must be nonempty and unique")
        if totals != windows or len(totals) != len(self.totals):
            raise ValueError("Final counters must bind the exact window set")
        bindings = {row.window_id: row for row in self.windows}
        if any(row.epoch != self.epoch for row in self.windows):
            raise ValueError("Barrier cannot span process epochs")
        if any(
            row.profile_id != bindings[row.window_id].binding.profile_id
            or row.upload_bytes < bindings[row.window_id].baseline_upload_bytes
            or row.download_bytes
            < bindings[row.window_id].baseline_download_bytes
            for row in self.totals
        ):
            raise ValueError("Final totals cannot change binding or baseline")
        return self


class ManagedAdmissionAcknowledgement(ImmutableContract):
    window_id: EpochIdentity
    grant_id: int = Field(gt=0)
    process_epoch: EpochIdentity
    window_sha256: Sha256
    installation_sha256: Sha256
    provision_task_id: int = Field(gt=0)
    claim_token: str = Field(min_length=1)
    outcome: Literal["admitted", "failed"]
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")


class ManagedRuntimeReadiness(ImmutableContract):
    enabled: Literal[False] = False
    stage: Literal["storage_only"] = "storage_only"
    installation_proves_admission: Literal[False] = False
    paid_bootstrap_available: Literal[False] = False
    final_receipt_available: Literal[False] = False
    prerequisites: tuple[str, ...] = (
        "managed_lock_order_native_acceptance",
        "managed_strict_budget_deadline_acceptance",
        "managed_paid_admission_native_acceptance",
        "managed_final_receipt_native_acceptance",
    )
