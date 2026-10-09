from datetime import datetime
from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field, model_validator

from src.modules.network.core_runtime.domain.memberships import (
    InstalledProfileMembership,
)
from src.modules.network.core_runtime.domain.usage import RuntimeUsageSnapshot
from src.modules.network.cores.domain.exports import CoreArtifact

RuntimeAction = Literal[
    "validate", "apply", "restart", "stop", "rollback", "reconcile"
]
RuntimeStatus = Literal["unknown", "running", "stopped"]


class RuntimeCapacity(BaseModel):
    enabled: bool
    allow_start: bool
    scan_batch_size: int = Field(gt=0)
    scan_cron: str = Field(min_length=1)
    retry_seconds: int = Field(gt=0)
    claim_seconds: int = Field(gt=0)
    max_attempts: int = Field(gt=0)
    max_profiles: int = Field(gt=0)
    max_configurations: int = Field(gt=0)
    max_payload_bytes: int = Field(gt=0)


class RuntimeSearch(BaseDTO):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class RuntimeRevisionCreate(BaseDTO):
    expected_revision: int = Field(ge=1)
    mode: Literal["merged", "isolated"]


class RuntimeCommandCreate(BaseDTO):
    expected_revision: int = Field(ge=1)
    action: RuntimeAction
    reconcile_mode: Literal["observe", "restore"] | None = None
    revision_id: int | None = Field(default=None, gt=0)
    request_key: str = Field(min_length=8, max_length=128)
    reason: str = Field(min_length=1, max_length=250)

    @model_validator(mode="after")
    def reconcile_contract(self) -> "RuntimeCommandCreate":
        if (self.action == "reconcile") != (self.reconcile_mode is not None):
            raise ValueError("Only reconcile requires a mode")
        return self


class RuntimeAcknowledgement(BaseDTO):
    claim_token: str = Field(min_length=32, max_length=128)
    outcome: Literal["succeeded", "failed"]
    error_code: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9_]{1,64}$"
    )
    observed_revision_id: int | None = Field(default=None, gt=0)
    observed_status: RuntimeStatus
    bundle_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    usage_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    process_epoch: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9_-]{32,128}$"
    )

    @model_validator(mode="after")
    def failure_reason(self) -> "RuntimeAcknowledgement":
        if (self.outcome == "failed") != (self.error_code is not None):
            raise ValueError("Only failures require an error code")
        return self


class RuntimeClaim(BaseModel):
    command_id: int
    core_id: int
    core_kind: str
    action: RuntimeAction
    reconcile_mode: Literal["observe", "restore"] | None = None
    revision_id: int | None
    bundle_sha256: str | None
    claim_token: str
    claim_until: datetime
    artifacts: list[CoreArtifact]
    memberships: list[InstalledProfileMembership] | None = None
    membership_sha256: str | None = None
    usage: RuntimeUsageSnapshot | None = None
    usage_sha256: str | None = None
