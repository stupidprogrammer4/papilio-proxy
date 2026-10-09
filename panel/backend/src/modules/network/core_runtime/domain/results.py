from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from src.modules.network.core_runtime.domain.dtos import (
    RuntimeAction,
    RuntimeStatus,
)
from src.modules.network.core_runtime.domain.usage import (
    RuntimeUsageCapability,
)


class RuntimeObservationFields(BaseModel):
    automation_paused: bool
    last_observed_at: datetime | None

    @field_validator("last_observed_at")
    @classmethod
    def observation_utc(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )


class RuntimeStateOut(RuntimeObservationFields):
    observed_process_epoch: str | None = None
    id: int | None
    core_id: int
    revision: int
    desired_revision_id: int | None
    applied_revision_id: int | None
    validated_revision_id: int | None
    observed_status: RuntimeStatus
    enabled: bool
    allow_start: bool
    start_blocked_reason: str | None = None
    allowed_actions: list[RuntimeAction]
    usage: RuntimeUsageCapability


class RuntimeUsageObservationOut(BaseModel):
    core_id: int
    runtime_revision_id: int
    observed_status: Literal["running", "stopped"]
    last_observed_at: datetime


class RuntimeHistoryFields(BaseModel):
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def history_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class RuntimeRevisionOut(RuntimeHistoryFields):
    id: int
    core_id: int
    created_by_staff_id: int | None
    mode: Literal["merged", "isolated"]
    bundle_sha256: str
    membership_sha256: str | None = None
    usage_sha256: str | None = None
    artifact_count: int


class RuntimeCommandOut(RuntimeHistoryFields):
    id: int
    core_id: int
    node_id: int
    purpose: Literal["operator", "provisioning"]
    action: RuntimeAction
    reconcile_mode: Literal["observe", "restore"] | None
    created_by_staff_id: int | None
    revision_id: int | None
    state: Literal["queued", "leased", "succeeded", "failed"]
    request_key: str
    reason: str
    error_code: str | None
    claim_until: datetime | None

    @field_validator("claim_until")
    @classmethod
    def lease_utc(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )
