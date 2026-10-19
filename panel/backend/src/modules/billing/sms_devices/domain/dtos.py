import re
from datetime import datetime
from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator, model_validator


class SmsDeviceWrite(BaseDTO):
    parser_profile_id: int | None = Field(default=None, gt=0)
    settlement_identity_mode: Literal[
        "bank_reference_required", "trusted_origin_fingerprint"
    ] = "bank_reference_required"

    approval_mode: Literal["manual", "unique_sms"] = "manual"
    destination_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def settlement_destination(self) -> "SmsDeviceWrite":
        if self.approval_mode == "unique_sms" and self.destination_id is None:
            raise ValueError(
                "Automatic SMS approval requires the receiving destination"
            )
        return self

    label: str = Field(min_length=2, max_length=100)
    senders: list[str] = Field(min_length=1)
    expires_at: datetime
    is_active: bool
    expected_revision: int | None = Field(default=None, gt=0)

    @field_validator("senders")
    @classmethod
    def distinct_senders(cls, value: list[str]) -> list[str]:
        if any(not sender.strip() or len(sender) > 100 for sender in value):
            raise ValueError("Sender names must contain 1–100 characters")
        return sorted(set(sender.strip() for sender in value))

    @field_validator("expires_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Device expiry requires a timezone")
        return value


class SmsDeviceSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class SmsDeviceRevision(BaseDTO):
    expected_revision: int = Field(gt=0)


class SmsDeviceStatusReport(BaseDTO):
    pending_event_count: int | None = Field(default=None, ge=0, le=10000)
    permission_granted: bool
    delivery_state: Literal[
        "ready", "paused", "retrying", "storage_error", "queue_full"
    ]
    last_acknowledged_event_id: str | None = Field(
        default=None, min_length=8, max_length=128
    )
    last_error_code: (
        Literal[
            "api_rejected",
            "network_unavailable",
            "api_unavailable",
            "local_storage",
            "queue_capacity",
            "settings_invalid",
            "job_schedule_failed",
        ]
        | None
    ) = None

    @field_validator("last_acknowledged_event_id")
    @classmethod
    def safe_event_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Acknowledged event ID has an invalid format")
        return value
