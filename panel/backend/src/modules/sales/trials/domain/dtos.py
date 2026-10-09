from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator


class TrialPolicy(BaseDTO):
    enabled: bool
    plan_id: int | None = Field(default=None, gt=0)
    eligibility: Literal["no_paid_purchase", "any_customer"]
    concurrent_mode: Literal["reject_active", "allow_multiple"]
    max_claims_per_customer: int = Field(gt=0)
    cooldown_seconds: int = Field(ge=0)
    quota_bytes: int = Field(gt=0, le=9223372036854775807)
    duration_days: int = Field(gt=0)

    @model_validator(mode="after")
    def enabled_source(self) -> "TrialPolicy":
        if self.enabled and self.plan_id is None:
            raise ValueError("An enabled trial requires a source plan")
        return self


class TrialClaim(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)
