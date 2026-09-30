from __future__ import annotations

from dataclasses import dataclass


class PaymentProviderUnavailable(RuntimeError):
    """The provider result cannot be trusted or obtained right now."""


@dataclass(frozen=True, slots=True)
class ProviderVerification:
    """A provider observation, not an order settlement or entitlement."""

    authority: str
    status: str
    transaction_id: str
    amount_rial: int
    paid_at: str | None

    @property
    def verified(self) -> bool:
        # KPay does not document a status enum. Fail closed for unknown values.
        return self.status == "paid" and self.paid_at is not None
