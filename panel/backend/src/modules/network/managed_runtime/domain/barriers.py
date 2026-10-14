"""Original single-window settlement and durable predecessor acceptance."""

from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator

from src.modules.network.managed_runtime.domain.contracts import (
    ByteCount,
    EpochIdentity,
    ImmutableContract,
    ManagedPredecessor,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedSnapshotReceiptWire,
)


class ManagedWindowFinalSubmission(BaseDTO):
    receipt: ManagedSnapshotReceiptWire
    original_receipt: str = Field(min_length=1)


class ManagedWindowFinalOut(ImmutableContract):
    window_id: EpochIdentity
    grant_id: int = Field(gt=0)
    acceptance: ManagedPredecessor
    upload_bytes: ByteCount
    download_bytes: ByteCount


class ManagedWindowFinalBatchItemCreate(BaseDTO):
    window_id: EpochIdentity
    request_key: str = Field(min_length=8, max_length=128)
    submission: ManagedWindowFinalSubmission


class ManagedWindowFinalBatchCreate(BaseDTO):
    batch_request_key: str = Field(min_length=8, max_length=128)
    windows: list[ManagedWindowFinalBatchItemCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_items(
        self,
    ) -> "ManagedWindowFinalBatchCreate":
        window_ids = [item.window_id for item in self.windows]
        request_keys = [item.request_key for item in self.windows]
        barrier_ids = [
            item.submission.receipt.barrier_id for item in self.windows
        ]
        if len(window_ids) != len(set(window_ids)):
            raise ValueError("Each window may appear once in a batch.")
        if len(request_keys) != len(set(request_keys)):
            raise ValueError("Each request key may appear once in a batch.")
        if len(barrier_ids) != len(set(barrier_ids)):
            raise ValueError("Each barrier may appear once in a batch.")
        return self


class ManagedWindowFinalBatchItemOut(ImmutableContract):
    window_id: EpochIdentity
    result: ManagedWindowFinalOut


class ManagedWindowFinalBatchOut(ImmutableContract):
    batch_request_key: str
    windows: list[ManagedWindowFinalBatchItemOut]
