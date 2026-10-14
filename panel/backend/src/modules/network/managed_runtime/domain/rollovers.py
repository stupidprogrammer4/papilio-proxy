"""Replayable proof for a fresh CLOSED process epoch after finality."""

from datetime import datetime

from papilio.schemas.inputs import BaseDTO
from pydantic import Field

from src.modules.network.managed_runtime.domain.contracts import (
    EpochIdentity,
    ImmutableContract,
    Sha256,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedClosedStartupReceiptWire,
)


class ManagedEpochRolloverSubmission(BaseDTO):
    request_id: EpochIdentity
    receipt: ManagedClosedStartupReceiptWire
    original_receipt: str = Field(min_length=1)


class ManagedEpochRolloverOut(ImmutableContract):
    installation_id: int
    previous_epoch_id: int
    previous_process_epoch: EpochIdentity
    epoch_id: int
    process_epoch: EpochIdentity
    request_id: EpochIdentity
    request_sha256: Sha256
    receipt_sha256: Sha256
    observed_at: datetime
    admission_available: bool = False


class ManagedInstallationEpochCount(ImmutableContract):
    installation_id: int = Field(gt=0)
    observed_count: int = Field(ge=0)
    count_capped: bool
