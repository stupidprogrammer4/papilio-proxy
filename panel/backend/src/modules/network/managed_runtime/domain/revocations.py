"""Exact historical epoch revocation and its native acceptance."""

from datetime import datetime
from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field

from src.modules.network.managed_runtime.domain.contracts import (
    EpochIdentity,
    ImmutableContract,
    Sha256,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedBindingWire,
    ManagedInstallationWire,
    ManagedSnapshotReceiptWire,
    ManagedWindowWire,
)


class ManagedWindowRevokeRequest(ImmutableContract):
    epoch: EpochIdentity
    request_id: EpochIdentity
    barrier_id: EpochIdentity
    window_id: EpochIdentity
    binding: ManagedBindingWire


class ManagedWindowRevocationWire(ImmutableContract):
    receipt_version: Literal[1]
    state: Literal["historical_epoch_profile_revoked"]
    request: ManagedWindowRevokeRequest
    window: ManagedWindowWire
    installation: ManagedInstallationWire
    snapshot: ManagedSnapshotReceiptWire
    adapter_revision: int = Field(gt=0)
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    module: Literal["github.com/xtls/xray-core@v1.260327.0"]
    accounting_scope: Literal["decoded_managed_tcp_payload_admission"]
    startup_receipt_sha256: Sha256
    window_policy_sha256: Sha256
    observed_at: datetime
    admission_blocked: Literal[True]
    historical_only: Literal[True]
    api_authority: Literal[False]


class ManagedRevocationReceipt(ImmutableContract):
    epoch: EpochIdentity
    request_id: EpochIdentity
    profile_id: int = Field(gt=0)
    receipt_sha256: Sha256
    bytes: int = Field(gt=0)


class ManagedRevocationSubmission(BaseDTO):
    original_receipt: str = Field(min_length=1)
    receipt: ManagedRevocationReceipt


class ManagedRevocationOut(ImmutableContract):
    window_id: EpochIdentity
    provision_task_id: int = Field(gt=0)
    revocation_sha256: Sha256
    outcome: Literal["revoked"] = "revoked"
    observed_at: datetime
