import re
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator, model_validator


class ScheduleKey(StrEnum):
    CUSTOMER_HOLDS = "customer_holds"
    LIFECYCLE = "lifecycle"
    PROVISIONING = "provisioning"
    PAYMENTS = "payments"
    NODES = "nodes"
    ATTENTION = "attention"
    RENEWALS = "renewals"
    NOTIFICATIONS = "notifications"
    CHECKOUT = "checkout"
    CORE_RUNTIME = "core_runtime"
    CORE_PROVISIONING = "core_provisioning"


class ScheduleMode(StrEnum):
    CRON = "cron"
    INTERVAL = "interval"


class SchedulePolicy(BaseDTO):
    mode: ScheduleMode = ScheduleMode.CRON
    interval_seconds: int | None = Field(default=None, gt=0)
    enabled: bool
    cron: str | None = Field(min_length=9, max_length=120)
    timezone: str | None = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def valid_mode(self) -> "SchedulePolicy":
        if self.mode == ScheduleMode.CRON:
            if (
                self.cron is None
                or self.timezone is None
                or self.interval_seconds is not None
            ):
                raise ValueError("کرون به زمان‌بندی و منطقهٔ زمانی نیاز دارد.")
        elif (
            self.interval_seconds is None
            or self.cron is not None
            or self.timezone is not None
        ):
            raise ValueError("فاصلهٔ ثابت فقط به تعداد ثانیه نیاز دارد.")
        return self

    batch_size: int = Field(gt=0)
    recheck_seconds: int | None = Field(ge=1)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("منطقهٔ زمانی معتبر نیست.") from error
        return value

    @field_validator("cron")
    @classmethod
    def valid_cron(cls, value: str | None) -> str | None:
        if value is None:
            return None
        fields = value.split()
        bounds = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
        if len(fields) != len(bounds):
            raise ValueError("زمان‌بندی باید پنج بخش داشته باشد.")
        for field, (lower, upper) in zip(fields, bounds, strict=True):
            for part in field.split(","):
                if not re.fullmatch(r"(?:\*|\d+(?:-\d+)?)(?:/\d+)?", part):
                    raise ValueError("از عدد، بازه، ستاره و گام استفاده کنید.")
                span, *step = part.split("/")
                if step and not 1 <= int(step[0]) <= upper - lower + 1:
                    raise ValueError("گام زمان‌بندی معتبر نیست.")
                if span != "*":
                    numbers = [int(item) for item in span.split("-")]
                    if not all(lower <= item <= upper for item in numbers):
                        raise ValueError("عدد زمان‌بندی خارج از بازه است.")
                    if len(numbers) == 2 and numbers[0] > numbers[1]:
                        raise ValueError("بازهٔ زمان‌بندی معکوس است.")
        return " ".join(fields)


class ScheduleWrite(BaseDTO):
    expected_revision: int = Field(ge=0)
    values: SchedulePolicy
    reason: str = Field(min_length=3, max_length=250)


class ScheduleHistorySearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
