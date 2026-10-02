from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReceiptOrder:
    order_id: str
    authority: str
    transaction_id: str
    amount_rial: int


@dataclass(frozen=True, slots=True)
class ReceiptPaymentPage:
    amount_rial: int
    final_amount_rial: int
    card_number: str
    owner_name: str
    remaining_seconds: int
    status: str


class ReceiptUnavailable(RuntimeError):
    """Receipt submission is unavailable or not bound to an eligible order."""
