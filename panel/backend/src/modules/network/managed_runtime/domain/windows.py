"""One initial reservation; successors remain unavailable."""

from datetime import datetime

from papilio.schemas.inputs import BaseDTO
from pydantic import Field

from src.modules.network.managed_runtime.domain.contracts import (
    EpochIdentity,
    ImmutableContract,
    Sha256,
)
from src.modules.network.managed_runtime.domain.wire import ManagedWindowWire


class ManagedInitialWindowCreate(BaseDTO):
    provision_task_id: int | None = Field(default=None, gt=0)
    profile_id: int = Field(gt=0)
    generation: int = Field(ge=0)
    process_epoch: EpochIdentity
    request_key: str = Field(min_length=8, max_length=128)
    requested_bytes: int = Field(gt=0, le=2**63 - 1)


class ManagedProvisionClaim(ImmutableContract):
    task_id: int = Field(gt=0)
    request_id: int = Field(gt=0)
    claim_token: str = Field(min_length=32, max_length=128)
    claim_until: datetime


class ManagedInitialWindowOut(ImmutableContract):
    id: int
    window_sha256: Sha256
    original_window: str
    window: ManagedWindowWire
    provision_claim: ManagedProvisionClaim | None = None
