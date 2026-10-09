from dataclasses import dataclass

from pydantic import Field, model_validator

from src.modules.billing.destinations.domain.results import PaymentInstruction
from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentIdentifierCode4,
    PaymentIdentifierMode,
    PositiveRialAmount,
    validate_payment_amount_evidence,
)
from src.modules.billing.wallet.domain.models import WalletEntryModel


@dataclass(frozen=True, slots=True)
class WalletLedgerFacts:
    customer_id: int
    entry: WalletEntryModel


class TopupPaymentInstructionRead(PaymentInstruction):
    topup_id: int = Field(gt=0)
    requested_amount_rial: PositiveRialAmount
    payable_amount_rial: PositiveRialAmount
    payment_identifier_mode: PaymentIdentifierMode
    payment_identifier_code4: PaymentIdentifierCode4 | None

    @model_validator(mode="after")
    def valid_payment_amount(self) -> "TopupPaymentInstructionRead":
        validate_payment_amount_evidence(
            self.payable_amount_rial,
            self.requested_amount_rial,
            self.payment_identifier_mode,
            self.payment_identifier_code4,
        )
        return self
