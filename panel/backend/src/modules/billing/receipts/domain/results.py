from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from src.modules.billing.receipts.domain.extraction import (
    ReceiptExtractionFields,
)


class ReceiptDetails(BaseModel):
    id: int
    topup_id: int
    media_type: str
    size_bytes: int
    created_at: datetime
    ocr_status: Literal["not_requested", "pending", "complete", "failed"] = (
        "pending"
    )
    extraction: ReceiptExtractionFields | None = None

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
