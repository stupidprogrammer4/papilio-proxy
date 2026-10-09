from datetime import UTC, datetime

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator

from src.modules.billing.sms_origins.domain.contracts import DeclaredSmsOrigin


class SmsReceived(BaseDTO):
    origin: DeclaredSmsOrigin | None = None
    event_id: str = Field(min_length=8, max_length=128)
    sender: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=5, max_length=4000)
    sent_at: datetime

    @field_validator("sent_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SMS timestamp must include timezone")
        try:
            utc = value.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise ValueError(
                "SMS timestamp is outside supported UTC range"
            ) from error
        if utc.year < 1000:
            raise ValueError("SMS timestamp is outside supported UTC range")
        return value


class SmsSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
