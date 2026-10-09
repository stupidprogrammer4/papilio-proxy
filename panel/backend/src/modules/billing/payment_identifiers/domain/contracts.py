from dataclasses import dataclass
from typing import Annotated, Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field, model_validator

RIAL_SUFFIX_MODULUS = 10_000
PERSISTED_RIAL_MAXIMUM = 2**63 - 1
PaymentIdentifierMode = Literal["exact_requested", "rial_suffix4"]
PaymentIdentifierCode4 = Annotated[str, Field(pattern=r"^[0-9]{4}$")]
PositiveRialAmount = Annotated[int, Field(gt=0, le=PERSISTED_RIAL_MAXIMUM)]


class PaymentIdentifierPolicy(BaseDTO):
    mode: PaymentIdentifierMode = "exact_requested"
    max_adjustment_rial: int = Field(ge=0)
    amount_step_rial: int = Field(gt=0, le=RIAL_SUFFIX_MODULUS)

    @model_validator(mode="after")
    def valid_step(self) -> "PaymentIdentifierPolicy":
        if RIAL_SUFFIX_MODULUS % self.amount_step_rial != 0:
            raise ValueError(
                "Payable amount step must divide the four-digit pool"
            )
        return self


class PaymentIdentifierCapacity(BaseModel):
    max_adjustment_rial: int = Field(ge=0)
    max_candidate_amounts: int = Field(gt=0)
    max_active_codes: int = Field(gt=0, le=RIAL_SUFFIX_MODULUS)


@dataclass(frozen=True, slots=True)
class PaymentAmountFacts:
    historical_amounts: tuple[int, ...]
    active_codes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PaymentAmountAllocation:
    requested_amount_rial: int
    payable_amount_rial: int
    mode: PaymentIdentifierMode
    code4: str | None
    reserve_amount: bool = False


class PaymentIdentifierCapabilities(BaseModel):
    capacity: PaymentIdentifierCapacity | None
    supported_modes: list[PaymentIdentifierMode]
    suffix_digits: int
    suffix_modulus: int


def validate_payment_amount_evidence(
    payable: int,
    requested: int | None,
    mode: PaymentIdentifierMode,
    code4: str | None,
) -> None:
    if requested is not None and payable < requested:
        raise ValueError("Payable amount cannot be below requested credit")
    if mode == "rial_suffix4":
        if code4 != f"{payable % RIAL_SUFFIX_MODULUS:04d}":
            raise ValueError(
                "Payment identifier must equal the last four rial digits"
            )
    elif code4 is not None:
        raise ValueError(
            "Exact requested amount has no allocated payment identifier"
        )
