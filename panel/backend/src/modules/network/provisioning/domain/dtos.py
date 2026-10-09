from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator


class ProvisioningSearch(BaseQuery):
    core_id: int | None = Field(default=None, gt=0)
    actionable: bool = False
    subscription_id: int | None = Field(default=None, gt=0)
    node_id: int | None = Field(default=None, gt=0)
    state: str | None = Field(default=None, max_length=32)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class ProvisionAcknowledgement(BaseDTO):
    runtime_revision_id: int | None = Field(default=None, gt=0)
    membership_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    claim_token: str = Field(min_length=32, max_length=128)
    outcome: Literal["applied", "failed", "revoked"]
    error_code: str | None = Field(
        default=None, max_length=64, pattern=r"^[a-z0-9_]+$"
    )

    @model_validator(mode="after")
    def require_error(self) -> "ProvisionAcknowledgement":
        if (self.outcome == "failed") != (self.error_code is not None):
            raise ValueError("Failed outcomes require a safe error code")
        return self


class ProvisioningRetry(BaseDTO):
    reason: str = Field(min_length=3, max_length=250)
