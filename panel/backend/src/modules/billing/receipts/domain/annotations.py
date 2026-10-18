from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ReceiptCorrectionFields(BaseModel):
    amount_rial: int | None = Field(
        default=None, ge=0, le=9_223_372_036_854_775_807
    )
    currency: Literal["rial", "toman"] | None = None
    destination_kind: Literal["card", "iban", "account"] | None = None
    visible_destination: str | None = Field(default=None, max_length=128)
    bank_namespace: str | None = Field(default=None, max_length=64)
    bank_reference: str | None = Field(default=None, max_length=128)
    occurred_at_utc: datetime | None = None
    transaction_status_claim: str | None = Field(default=None, max_length=64)

    @field_validator("occurred_at_utc")
    @classmethod
    def utc_transaction_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Transaction time must include a timezone")
        return value.astimezone(UTC) if value is not None else value


class ReceiptAnnotationWrite(BaseModel):
    expected_revision: int = Field(ge=0, le=2_147_483_646)
    fields: ReceiptCorrectionFields
    reason: str = Field(min_length=1, max_length=250)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A correction reason is required")
        return normalized


class ReceiptAnnotation(BaseModel):
    id: int
    receipt_id: int
    revision: int
    staff_id: int
    created_at: datetime
    fields: ReceiptCorrectionFields
    reason: str

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )
