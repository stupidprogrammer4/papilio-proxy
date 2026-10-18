from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReceiptOcrLine(BaseModel):
    text: str = Field(min_length=1)
    confidence_milli: int = Field(ge=0, le=1000)
    region: tuple[tuple[int, int], ...] = ()


class ReceiptOcrResult(BaseModel):
    lines: tuple[ReceiptOcrLine, ...] = ()
    failure_code: (
        Literal[
            "provider_rejected",
            "invalid_provider_response",
            "provider_response_too_large",
        ]
        | None
    ) = None


class ReceiptFieldEvidence(BaseModel):
    line_indexes: tuple[int, ...] = Field(min_length=1)
    text: str = Field(min_length=1)
    confidence_milli: int = Field(ge=0, le=1000)
    region: tuple[tuple[int, int], ...] = ()


class ReceiptExtractionFields(BaseModel):
    amount_raw: str | None = None
    amount_rial: int | None = Field(default=None, ge=0)
    currency: Literal["rial", "toman"] | None = None
    destination_kind: Literal["card", "iban", "account"] | None = None
    visible_destination: str | None = None
    destination_masked: str | None = None
    bank_namespace: str | None = None
    bank_reference: str | None = None
    occurred_at_raw: str | None = None
    occurred_at_utc: datetime | None = None
    calendar: Literal["jalali", "gregorian"] | None = None
    timezone: str | None = None
    transaction_status_claim: str | None = None
    field_evidence: dict[str, ReceiptFieldEvidence] = Field(
        default_factory=dict
    )
    warnings: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
