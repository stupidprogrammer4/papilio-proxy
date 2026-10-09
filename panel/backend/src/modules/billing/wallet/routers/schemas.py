from datetime import UTC, datetime

from pydantic import BaseModel, model_validator

from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentIdentifierCode4,
    PaymentIdentifierMode,
    PositiveRialAmount,
    validate_payment_amount_evidence,
)
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.billing.wallet.domain.results import WalletLedgerFacts


class TopupOut(BaseModel):
    id: int
    customer_id: int
    amount_rial: PositiveRialAmount
    requested_amount_rial: PositiveRialAmount | None
    payment_identifier_mode: PaymentIdentifierMode
    payment_identifier_code4: PaymentIdentifierCode4 | None
    status: str
    bank_reference: str | None
    approved_by_staff_id: int | None
    approved_by_device_id: int | None
    approved_by_sms_id: int | None

    @model_validator(mode="after")
    def valid_payment_amount(self) -> "TopupOut":
        validate_payment_amount_evidence(
            self.amount_rial,
            self.requested_amount_rial,
            self.payment_identifier_mode,
            self.payment_identifier_code4,
        )
        return self

    @classmethod
    def from_model(cls, item: TopupModel) -> "TopupOut":
        return cls.model_validate(item, from_attributes=True)


class WalletBalanceOut(BaseModel):
    customer_id: int
    balance_rial: int


class WalletEntryOut(BaseModel):
    id: int
    customer_id: int
    amount_rial: int
    balance_after_rial: int
    reference: str
    reason: str
    created_at: datetime

    @classmethod
    def from_facts(cls, item: WalletLedgerFacts) -> "WalletEntryOut":
        assert item.entry.created_at is not None
        return cls(
            id=item.entry.id,
            customer_id=item.customer_id,
            amount_rial=item.entry.amount_rial,
            balance_after_rial=item.entry.balance_after_rial,
            reference=item.entry.reference,
            reason=item.entry.reason,
            created_at=item.entry.created_at.replace(tzinfo=UTC),
        )
