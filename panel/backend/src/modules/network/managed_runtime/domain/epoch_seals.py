"""Finite epoch termination evidence; acceptance does not authorize restart."""

from datetime import datetime
from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator

from src.modules.network.managed_runtime.domain.contracts import (
    EpochIdentity,
    ImmutableContract,
    Sha256,
)
from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorWindowFacts,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedBindingWire,
    ManagedInstallationWire,
    ManagedSnapshotReceiptWire,
    ManagedTotalsWire,
    ManagedWindowWire,
)


class ManagedEpochSealLimits(ImmutableContract):
    max_windows_per_epoch: int = Field(gt=0)
    max_receipt_bytes: int = Field(gt=0)
    max_epochs: int = Field(gt=0, default=1)


class ManagedEpochSealPolicy(ImmutableContract):
    mode: Literal["disabled", "strict"] = "disabled"
    limits: ManagedEpochSealLimits | None = None

    @model_validator(mode="after")
    def explicit_limits(self) -> "ManagedEpochSealPolicy":
        if self.mode == "strict" and self.limits is None:
            raise ValueError("Epoch sealing requires explicit limits")
        return self


class ManagedEpochSealProfileRequest(ImmutableContract):
    binding: ManagedBindingWire
    membership_sha256: Sha256
    profile_sha256: Sha256


class ManagedEpochSealRequest(ImmutableContract):
    epoch: EpochIdentity
    request_id: EpochIdentity
    profiles: tuple[ManagedEpochSealProfileRequest, ...]

    @model_validator(mode="after")
    def full_sorted_profiles(self) -> "ManagedEpochSealRequest":
        ids = tuple(row.binding.profile_id for row in self.profiles)
        if not ids or ids != tuple(sorted(set(ids))):
            raise ValueError(
                "Seal profiles must be nonempty, unique and sorted"
            )
        return self


class ManagedEpochSealProfile(ManagedEpochSealProfileRequest):
    phase: Literal["sealed"]
    never_admitted: bool
    window: ManagedWindowWire | None = None
    snapshot: ManagedSnapshotReceiptWire | None = None
    totals: ManagedTotalsWire
    active_operations: Literal[0]
    resources: Literal[0]
    reserved_bytes: Literal[0]
    active_reservations: Literal[0]
    admission_operations: Literal[0]

    @model_validator(mode="after")
    def exact_terminal_state(self) -> "ManagedEpochSealProfile":
        if self.totals.binding != self.binding:
            raise ValueError("Seal totals belong to another binding")
        if self.never_admitted:
            if (
                self.window is not None
                or self.snapshot is not None
                or self.totals.upload_bytes
                or self.totals.download_bytes
                or self.totals.unadmitted_upload_bytes
                or self.totals.unadmitted_download_bytes
            ):
                raise ValueError(
                    "Never-admitted profile has terminal activity"
                )
        elif self.window is None or self.snapshot is None:
            raise ValueError(
                "Admitted profile requires window and final snapshot"
            )
        return self


class ManagedEpochSealWire(ImmutableContract):
    receipt_version: Literal[1]
    state: Literal["historical_epoch_sealed"]
    request: ManagedEpochSealRequest
    installation: ManagedInstallationWire
    adapter_revision: int = Field(gt=0)
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    module: Literal["github.com/xtls/xray-core@v1.260327.0"]
    accounting_scope: Literal["decoded_managed_tcp_payload_admission"]
    enforcement_sha256: Sha256
    window_policy_sha256: Sha256
    startup_receipt_sha256: Sha256
    profiles: tuple[ManagedEpochSealProfile, ...]
    admission_blocked: Literal[True]
    historical_only: Literal[True]
    api_authority: Literal[False]
    observed_at: datetime

    @model_validator(mode="after")
    def exact_request_profiles(self) -> "ManagedEpochSealWire":
        if self.observed_at.tzinfo is None:
            raise ValueError("Seal observation requires timezone")
        projected = tuple(
            ManagedEpochSealProfileRequest(
                binding=row.binding,
                membership_sha256=row.membership_sha256,
                profile_sha256=row.profile_sha256,
            )
            for row in self.profiles
        )
        if projected != self.request.profiles:
            raise ValueError("Seal proof changes requested membership")
        return self


class ManagedEpochSealReceipt(ImmutableContract):
    epoch: EpochIdentity
    request_id: EpochIdentity
    receipt_sha256: Sha256
    bytes: int = Field(gt=0)


class ManagedEpochSealSubmission(BaseDTO):
    original_receipt: str = Field(min_length=1)
    receipt: ManagedEpochSealReceipt


class ManagedEpochSealRecoveryCreate(BaseDTO):
    request_id: EpochIdentity


class ManagedEpochSealRecoveryWindow(ImmutableContract):
    window_id: EpochIdentity
    grant_id: int = Field(gt=0)
    window_sha256: Sha256
    barrier_id: EpochIdentity
    snapshot_sha256: Sha256
    upload_bytes: int = Field(ge=0, le=2**63 - 1)
    download_bytes: int = Field(ge=0, le=2**63 - 1)


class ManagedEpochSealRecoveryReceipt(ImmutableContract):
    receipt_version: Literal[1]
    state: Literal["api_recovered_from_accepted_finality"]
    epoch: EpochIdentity
    request_id: EpochIdentity
    startup_receipt_sha256: Sha256
    windows: tuple[ManagedEpochSealRecoveryWindow, ...]


class ManagedEpochSealOut(ImmutableContract):
    id: int
    epoch: EpochIdentity
    installation_id: int
    request_id: EpochIdentity
    receipt_sha256: Sha256
    acceptance_id: EpochIdentity
    accepted_at: datetime


class ManagedEpochSealGrantFacts(ImmutableContract):
    id: int
    subscription_id: int
    profile_id: int
    node_id: int
    generation: int
    configuration_revision: int
    mode: str
    process_epoch: str | None
    allocated_bytes: int
    upload_bytes: int
    download_bytes: int
    sequence: int
    is_closed: bool


class ManagedEpochSealBarrierFacts(ImmutableContract):
    id: int
    epoch_id: int
    barrier_id: str
    acceptance_id: str
    snapshot_sha256: str
    request_sha256: str
    encrypted_receipt: str


class ManagedEpochSealRead(ImmutableContract):
    windows: tuple[ManagedSuccessorWindowFacts, ...]
    grants: tuple[ManagedEpochSealGrantFacts, ...]
    barriers: tuple[ManagedEpochSealBarrierFacts, ...]


class ManagedEpochSealEpochHint(ImmutableContract):
    id: int
    installation_id: int
    process_epoch: str
