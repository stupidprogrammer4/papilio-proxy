from datetime import UTC, datetime

from pydantic import BaseModel, field_validator


class GrantOut(BaseModel):
    id: int
    subscription_id: int
    profile_id: int
    node_id: int
    generation: int
    configuration_revision: int
    mode: str
    allocated_bytes: int
    upload_bytes: int
    download_bytes: int
    sequence: int
    is_closed: bool
    sampled_at: datetime | None
    valid_until: datetime
    installed_revision_id: int | None
    usage_sha256: str | None
    process_epoch: str | None

    @field_validator("sampled_at", "valid_until")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )


class EventOut(BaseModel):
    id: int
    grant_id: int
    subscription_id: int
    node_id: int
    generation: int
    sequence: int
    upload_bytes: int
    download_bytes: int
    delta_upload_bytes: int
    delta_download_bytes: int
    delta_bytes: int
    final: bool
    sampled_at: datetime

    @field_validator("sampled_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
