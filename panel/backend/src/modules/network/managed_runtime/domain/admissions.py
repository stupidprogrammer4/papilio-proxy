"""Original historical strict admission and its native acceptance."""

from datetime import datetime
from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field

from src.modules.network.managed_runtime.domain.contracts import (
    EpochIdentity,
    ImmutableContract,
    Sha256,
)
from src.modules.network.managed_runtime.domain.wire import ManagedWindowWire


class ManagedStrictAdmissionWire(ImmutableContract):
    receipt_version: Literal[1]
    state: Literal["historical_strict_window_admission"]
    window: ManagedWindowWire
    window_sha256: Sha256
    adapter_revision: int
    source_commit: str
    module: Literal["github.com/xtls/xray-core@v1.260327.0"]
    accounting_scope: Literal["decoded_managed_tcp_payload_admission"]
    window_policy_sha256: Sha256
    startup_receipt_sha256: Sha256
    observed_at: datetime
    budget_enforced: Literal[True]
    deadline_enforced: Literal[True]
    historical_only: Literal[True]
    api_authority: Literal[False]


class ManagedAdmissionReceipt(ImmutableContract):
    epoch: EpochIdentity
    window_id: EpochIdentity
    receipt_sha256: Sha256
    bytes: int = Field(gt=0)


class ManagedAdmissionSubmission(BaseDTO):
    claim_token: str = Field(min_length=32, max_length=128)
    original_receipt: str = Field(min_length=1)
    receipt: ManagedAdmissionReceipt


class ManagedAdmissionOut(ImmutableContract):
    window_id: EpochIdentity
    provision_task_id: int = Field(gt=0)
    admission_sha256: Sha256
    outcome: Literal["applied"] = "applied"
    observed_at: datetime
