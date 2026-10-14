"""One initial reservation; successors remain unavailable."""

from datetime import datetime

from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator

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


class ManagedInitialWindowBatchCreate(BaseDTO):
    batch_request_key: str = Field(min_length=8, max_length=128)
    windows: list[ManagedInitialWindowCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_profiles_and_requests(
        self,
    ) -> "ManagedInitialWindowBatchCreate":
        profile_ids = [window.profile_id for window in self.windows]
        request_keys = [window.request_key for window in self.windows]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("Each profile may appear once in a batch.")
        if len(request_keys) != len(set(request_keys)):
            raise ValueError("Each window request key must be unique.")
        if len({window.process_epoch for window in self.windows}) != 1:
            raise ValueError("A batch must belong to one process epoch.")
        return self


class ManagedInitialWindowBatchOut(ImmutableContract):
    batch_request_key: str
    windows: list["ManagedInitialWindowBatchItemOut"]


class ManagedInitialWindowBatchItemOut(ImmutableContract):
    profile_id: int = Field(gt=0)
    window: ManagedInitialWindowOut
