from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CoreProvisioningCapacity(BaseModel):
    mode: Literal["disabled", "installed_only", "enforced"]
    batch_size: int = Field(gt=0)
    scan_cron: str = Field(min_length=1)
    max_memberships: int = Field(gt=0)
    observation_seconds: int = Field(gt=0)
    max_attempts: int = Field(default=5, gt=0)
    retry_seconds: int = Field(default=5, gt=0)


class RuntimeProvisioningAttempt(BaseModel):
    attempts: int
    updated_at: datetime


class RuntimeProvisioningBudget(BaseModel):
    exhausted: bool
    retry_at: datetime | None = None


class InstalledProfileMembership(BaseModel):
    profile_id: int
    subscription_id: int
    generation: int
    configuration_id: int
    configuration_revision: int
    presence: Literal["present", "absent"]
    credential_sha256: str
    client_address: str | None
    artifact_filename: str
    artifact_sha256: str


class RuntimeEntitlementBinding(BaseModel):
    profile_id: int
    generation: int
    quota_bytes: int | None
    duration_days: int | None
    expires_at: datetime | None
    pending_activation: bool


class RuntimeMembershipSnapshot(BaseModel):
    memberships: list[InstalledProfileMembership]
    bindings: list[RuntimeEntitlementBinding]


class InstalledProfileProof(BaseModel):
    installed_revision_id: int
    membership_sha256: str
    membership: InstalledProfileMembership


class CoreProvisioningDecision(BaseModel):
    core_id: int
    state: Literal["blocked", "waiting", "queued", "installed"]
    reason_code: str | None = None
    command_id: int | None = None
    revision_id: int | None = None
