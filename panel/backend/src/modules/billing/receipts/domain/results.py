from datetime import UTC, datetime

from pydantic import BaseModel, field_validator


class ReceiptDetails(BaseModel):
    id: int
    topup_id: int
    media_type: str
    size_bytes: int
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )


class ReceiptDownload(BaseModel):
    content: bytes
    media_type: str
