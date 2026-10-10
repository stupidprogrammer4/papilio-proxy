"""Original single-window settlement and durable predecessor acceptance."""

from papilio.schemas.inputs import BaseDTO
from pydantic import Field

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
