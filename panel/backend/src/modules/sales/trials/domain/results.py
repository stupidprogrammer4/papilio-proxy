from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

from src.modules.sales.trials.domain.dtos import TrialPolicy


class TrialUsage(BaseModel):
    claims: int
    active_claims: int
    paid_purchases: int
    latest_claim_at: datetime | None


class TrialAvailability(BaseModel):
    policy: TrialPolicy
    capacity_valid: bool
    eligible: bool
    reason: str | None
    claims: int
    next_claim_at: datetime | None

    @field_validator("next_claim_at")
    @classmethod
    def utc_next_claim(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )
