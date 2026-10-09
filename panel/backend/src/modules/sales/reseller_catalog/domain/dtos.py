from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator


class AgreementPrice(BaseDTO):
    mode: Literal["catalog", "fixed", "discount"]
    fixed_price_rial: int | None = Field(default=None, ge=0)
    discount_bps: int | None = Field(default=None, ge=0, le=10_000)
    rounding: Literal["floor", "ceil", "nearest"]
    quantum_rial: int = Field(gt=0)

    @model_validator(mode="after")
    def require_mode_inputs(self) -> "AgreementPrice":
        if (self.fixed_price_rial is not None) != (self.mode == "fixed"):
            raise ValueError("A fixed price belongs only to fixed pricing")
        if (self.discount_bps is not None) != (self.mode == "discount"):
            raise ValueError("A discount belongs only to discount pricing")
        return self


class AgreementFields(BaseDTO):
    enabled: bool
    price: AgreementPrice


class AgreementCreate(AgreementFields):
    plan_id: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=250)


class AgreementWrite(AgreementFields):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=250)
