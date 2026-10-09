"""Captured wallet payment contracts and stateless private callbacks."""
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from papilio_telegram.checkout import CheckoutPaymentInstruction

PERSISTED_ID_MAXIMUM = 2**63 - 1
TELEGRAM_CALLBACK_BYTES = 64


@dataclass(frozen=True, slots=True)
class TopupFlowLimits:
    destination_page_size: int

    def __post_init__(self) -> None:
        if self.destination_page_size <= 0:
            raise ValueError("Top-up destination page size must be positive")


class WalletTopupRead(BaseModel):
    id: int = Field(gt=0, le=PERSISTED_ID_MAXIMUM)
    customer_id: int = Field(gt=0, le=PERSISTED_ID_MAXIMUM)
    amount_rial: int = Field(gt=0, le=PERSISTED_ID_MAXIMUM)
    requested_amount_rial: int | None = Field(
        default=None, gt=0, le=PERSISTED_ID_MAXIMUM
    )
    payment_identifier_mode: Literal["exact_requested", "rial_suffix4"]
    payment_identifier_code4: str | None = Field(
        default=None, pattern=r"^[0-9]{4}$"
    )
    status: Literal["pending", "approved", "rejected"]

    @model_validator(mode="after")
    def captured_amount(self) -> "WalletTopupRead":
        if self.requested_amount_rial is not None and (
            self.amount_rial < self.requested_amount_rial
        ):
            raise ValueError("Payable amount is below requested credit")
        if self.payment_identifier_mode == "rial_suffix4":
            if self.requested_amount_rial is None or (
                self.payment_identifier_code4 != f"{self.amount_rial % 10000:04d}"
            ):
                raise ValueError("Incomplete or mismatched payment identifier")
        elif self.payment_identifier_code4 is not None:
            raise ValueError("Exact requested amount cannot have a code")
        return self

    @property
    def original_amount_rial(self) -> int:
        return (
            self.requested_amount_rial
            if self.requested_amount_rial is not None
            else self.amount_rial
        )


class WalletTopupCreate(BaseModel):
    amount_rial: int = Field(gt=0, le=PERSISTED_ID_MAXIMUM)
    destination_id: int | None = Field(
        default=None, gt=0, le=PERSISTED_ID_MAXIMUM
    )
    request_key: str = Field(min_length=8, max_length=64)


class TopupPaymentInstruction(CheckoutPaymentInstruction):
    @model_validator(mode="after")
    def complete_topup_evidence(self) -> "TopupPaymentInstruction":
        if (
            self.topup_id is None
            or self.requested_amount_rial is None
            or self.payable_amount_rial is None
            or self.payment_identifier_mode is None
        ):
            raise ValueError("Captured top-up payment amount is required")
        return self


def callback_data(kind: str, *values: int) -> str:
    if not values or any(
        not 0 < value <= PERSISTED_ID_MAXIMUM for value in values
    ):
        raise ValueError("Callback identities must be positive and bounded")
    result = kind + ":" + ":".join(str(value) for value in values)
    if len(result.encode()) > TELEGRAM_CALLBACK_BYTES:
        raise ValueError("Callback exceeds Telegram protocol capacity")
    return result


def callback_values(value: str, kind: str, count: int) -> tuple[int, ...]:
    if len(value.encode()) > TELEGRAM_CALLBACK_BYTES:
        raise ValueError("Callback exceeds Telegram protocol capacity")
    parts = value.split(":")
    if len(parts) != count + 1 or parts[0] != kind or any(
        not part.isascii() or not part.isdigit() for part in parts[1:]
    ):
        raise ValueError("Malformed top-up callback")
    result = tuple(int(part) for part in parts[1:])
    if any(not 0 < item <= PERSISTED_ID_MAXIMUM for item in result):
        raise ValueError("Callback identities must be positive and bounded")
    return result
