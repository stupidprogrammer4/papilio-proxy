"""Bounded continuation of an already settled process-epoch window."""

from datetime import datetime
from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator

from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalOut,
)
from src.modules.network.managed_runtime.domain.contracts import (
    ByteCount,
    ImmutableContract,
    ManagedPredecessor,
    Sha256,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedSnapshotReceiptWire,
    ManagedWindowWire,
)


class ManagedSuccessorLimits(ImmutableContract):
    max_windows_per_profile_epoch: int = Field(gt=1)
    max_windows_per_epoch: int = Field(gt=1)
    max_epoch_seconds: int = Field(gt=0)
    max_requested_bytes: int = Field(gt=0, le=2**63 - 1)

    @model_validator(mode="after")
    def bounded_profile_capacity(self) -> "ManagedSuccessorLimits":
        if self.max_windows_per_profile_epoch > self.max_windows_per_epoch:
            raise ValueError("Profile windows exceed the epoch capacity")
        return self


class ManagedSuccessorPolicy(ImmutableContract):
    mode: Literal["disabled", "bounded"] = "disabled"
    limits: ManagedSuccessorLimits | None = None

    @model_validator(mode="after")
    def explicit_enabled_limits(self) -> "ManagedSuccessorPolicy":
        if self.mode == "bounded" and self.limits is None:
            raise ValueError("Bounded successors require explicit limits")
        return self


class ManagedSuccessorWindowCreate(BaseDTO):
    request_key: str = Field(min_length=8, max_length=128)
    requested_bytes: int = Field(gt=0, le=2**63 - 1)
    acceptance: ManagedPredecessor


class ManagedSuccessorWindowOut(ImmutableContract):
    id: int = Field(gt=0)
    window_sha256: Sha256
    original_window: str
    window: ManagedWindowWire


class ManagedSuccessorEvidence(ImmutableContract):
    """Detached accepted facts; callers establish DB finality under locks."""

    original_window: bytes
    window_sha256: Sha256
    window: ManagedWindowWire
    original_receipt: bytes
    receipt: ManagedSnapshotReceiptWire
    finality: ManagedWindowFinalOut


class ManagedSuccessorBaseline(ImmutableContract):
    upload_bytes: ByteCount
    download_bytes: ByteCount
    predecessor: ManagedPredecessor

    @model_validator(mode="after")
    def signed_cumulative_total(self) -> "ManagedSuccessorBaseline":
        if self.upload_bytes + self.download_bytes > 2**63 - 1:
            raise ValueError("Successor baseline exceeds signed counters")
        return self


class ManagedSuccessorWindowFacts(ImmutableContract):
    id: int
    epoch_id: int
    grant_id: int
    profile_id: int
    subscription_id: int
    provision_task_id: int | None
    encrypted_provision_claim: str | None
    generation: int
    window_id: str
    request_key: str
    request_sha256: str
    window_sha256: str
    baseline_upload_bytes: int
    baseline_download_bytes: int
    allocated_bytes: int
    issued_at: datetime
    valid_until: datetime
    predecessor_id: int | None
    encrypted_window: str


class ManagedSuccessorChainRead(ImmutableContract):
    windows: tuple[ManagedSuccessorWindowFacts, ...]


class ManagedSuccessorAdmissionFacts(ImmutableContract):
    window_id: int
    provision_task_id: int
    receipt_sha256: str
    outcome: str
    observed_at: datetime
    encrypted_receipt: str
