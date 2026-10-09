from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator

from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentIdentifierPolicy,
)

PaymentKind = Literal["card", "iban", "bank_account"]


class DestinationWrite(BaseDTO):
    expected_revision: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=100)
    kind: PaymentKind
    account: str = Field(min_length=1, max_length=100)
    recipient: str = Field(min_length=1, max_length=100)
    bank_name: str = Field(min_length=1, max_length=100)
    instructions: str | None = Field(default=None, max_length=2000)
    is_active: bool

    @model_validator(mode="after")
    def account_format(self) -> "DestinationWrite":
        if self.kind == "card" and (
            len(self.account) != 16
            or not self.account.isascii()
            or not self.account.isdigit()
        ):
            raise ValueError("A card destination requires 16 ASCII digits")
        if self.kind == "iban" and (
            not self.account.startswith("IR")
            or len(self.account) != 26
            or not self.account[2:].isascii()
            or not self.account[2:].isdigit()
        ):
            raise ValueError("An Iranian IBAN requires IR and 24 digits")
        return self


class DestinationSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    active: bool | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class CheckoutPolicy(BaseDTO):
    payment_identifier: PaymentIdentifierPolicy | None = None
    destination_mode: Literal["required", "optional", "legacy"]
    allowed_methods: list[PaymentKind] = Field(min_length=1)
    minimum_topup_rial: int = Field(gt=0)
    maximum_topup_rial: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self) -> "CheckoutPolicy":
        if self.minimum_topup_rial > self.maximum_topup_rial or len(
            set(self.allowed_methods)
        ) != len(self.allowed_methods):
            raise ValueError("Invalid checkout policy range or methods")
        return self
