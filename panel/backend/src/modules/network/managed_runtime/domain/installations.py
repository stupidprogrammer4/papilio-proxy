"""Issued expectations are separate from node observations and admission."""

from datetime import datetime
from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field

from src.modules.network.managed_runtime.domain.contracts import (
    ImmutableContract,
    ManagedRuntimeCapacity,
    Sha256,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedClosedProfileWire,
    ManagedClosedStartupReceiptWire,
    ManagedInstallationWire,
)


class ManagedAdapterPolicy(ImmutableContract):
    enabled: bool = False
    window_mode: Literal["disabled", "reserved"] = "disabled"
    paid_mode: Literal["disabled", "strict_admission"] = "disabled"
    adapter_revision: Literal[1] = 1
    source_commit: Literal["d2758a023cd7f4174a5a5fa4ff66e487d4342ba0"]
    executable_sha256: Sha256
    materials_sha256: Sha256
    enforcement_sha256: Sha256
    window_policy_sha256: Sha256
    capacity: ManagedRuntimeCapacity
    claim_seconds: int = Field(gt=0)
    observation_seconds: int = Field(gt=0)
    clock_skew_seconds: int = Field(ge=0)


class ManagedInstallationCreate(BaseDTO):
    runtime_revision_id: int = Field(gt=0)
    expected_runtime_revision: int = Field(gt=0)


class ManagedInstallationExpectation(ImmutableContract):
    runtime_revision_id: int = Field(gt=0)
    runtime_state_revision: int = Field(gt=0)
    claim_seconds: int = Field(gt=0)
    observation_seconds: int = Field(gt=0)
    clock_skew_seconds: int = Field(ge=0)
    capacity: ManagedRuntimeCapacity
    artifact_filename: str
    artifact_sha256: Sha256
    membership_sha256: Sha256
    installation: ManagedInstallationWire
    adapter_revision: int
    source_commit: str
    enforcement_sha256: Sha256
    window_policy_sha256: Sha256
    profiles: tuple[ManagedClosedProfileWire, ...]


class ManagedInstallationClaim(ImmutableContract):
    installation_id: int
    claim_token: str
    claim_until: datetime
    expectation: ManagedInstallationExpectation
    artifact_content: str


class ManagedClosedStartupAcknowledgement(BaseDTO):
    claim_token: str = Field(min_length=32, max_length=128)
    receipt: ManagedClosedStartupReceiptWire
    original_receipt: str = Field(min_length=1)


class ManagedInstallationOut(ImmutableContract):
    id: int
    node_id: int
    core_id: int
    runtime_revision_id: int
    installation_sha256: str
    state: Literal["issued", "leased", "installed_closed"]


class ManagedInstalledClosedOut(ImmutableContract):
    installation_id: int
    epoch_id: int
    process_epoch: str
    receipt_sha256: str
    observed_at: datetime
    admission_available: Literal[False] = False
