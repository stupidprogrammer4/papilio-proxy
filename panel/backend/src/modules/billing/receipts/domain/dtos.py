from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator


class ReceiptPolicy(BaseDTO):
    enabled: bool
    max_per_topup: int = Field(gt=0)
    allowed_formats: list[Literal["JPEG", "PNG", "WEBP"]] = Field(min_length=1)

    @field_validator("allowed_formats")
    @classmethod
    def distinct_formats(
        cls, values: list[Literal["JPEG", "PNG", "WEBP"]]
    ) -> list[Literal["JPEG", "PNG", "WEBP"]]:
        if len(set(values)) != len(values):
            raise ValueError("Receipt formats must be distinct")
        return values
