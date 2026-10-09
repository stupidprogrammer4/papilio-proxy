from datetime import datetime

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator


class UsageAllocation(BaseDTO):
    profile_id: int = Field(gt=0)
    generation: int = Field(ge=0)
    request_key: str = Field(min_length=8, max_length=128)
    requested_bytes: int = Field(gt=0)
    installed_revision_id: int | None = Field(default=None, gt=0)
    usage_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    process_epoch: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9_-]{32,128}$"
    )

    @model_validator(mode="after")
    def installation_proof(self) -> "UsageAllocation":
        values = (
            self.installed_revision_id,
            self.usage_sha256,
            self.process_epoch,
        )
        if any(value is not None for value in values) and any(
            value is None for value in values
        ):
            raise ValueError(
                "Installation proof requires revision, hash and epoch"
            )
        return self


class UsageReport(BaseDTO):
    event_id: str = Field(min_length=8, max_length=128)
    sequence: int = Field(gt=0, le=2**31 - 1)
    upload_bytes: int = Field(ge=0, le=2**63 - 1)
    download_bytes: int = Field(ge=0, le=2**63 - 1)
    sampled_at: datetime
    final: bool
    process_epoch: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9_-]{32,128}$"
    )

    @model_validator(mode="after")
    def aware_time(self) -> "UsageReport":
        if self.upload_bytes + self.download_bytes > 2**63 - 1:
            raise ValueError("Counters exceed the signed byte contract")
        if self.sampled_at.tzinfo is None:
            raise ValueError("Usage sample time must include its UTC offset")
        return self


class UsageSearch(BaseQuery):
    subscription_id: int | None = Field(default=None, gt=0)
    node_id: int | None = Field(default=None, gt=0)
    generation: int | None = Field(default=None, ge=0)
    since: datetime | None = None
    until: datetime | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def time_range(self) -> "UsageSearch":
        if any(
            value is not None and value.tzinfo is None
            for value in (self.since, self.until)
        ):
            raise ValueError("Usage filters require timezone-aware timestamps")
        if (
            self.since is not None
            and self.until is not None
            and self.since > self.until
        ):
            raise ValueError("Usage range is reversed")
        return self
