from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field


class FulfillmentPolicy(BaseDTO):
    renewal_trigger: Literal["expiry", "quota", "either"]
    automatic: bool
    activation: Literal["all", "any", "quorum"]
    minimum_successes: int = Field(gt=0)
    expiry_start: Literal["purchase", "activation"]
    failure_action: Literal["hold", "refund_wallet"]
    max_attempts: int = Field(gt=0)
    claim_seconds: int = Field(gt=0)
    retry_seconds: int = Field(gt=0)
    deadline_minutes: int = Field(gt=0)
    renewal_quota: Literal["reset", "carry_unused"]
    renewal_price: Literal["purchased", "current_plan"]


class QuotaPolicy(BaseDTO):
    mode: Literal["reported", "reserved"]
    grant_bytes: int = Field(gt=0)
    grant_seconds: int = Field(gt=0)
    report_max_age_seconds: int = Field(gt=0)
    report_future_seconds: int = Field(ge=0)
