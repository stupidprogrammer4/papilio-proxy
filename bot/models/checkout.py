from dataclasses import dataclass

from bot.models.payments import PaymentInitiation


class CheckoutUnavailable(RuntimeError):
    """No checkout may be issued or guessed when its state is uncertain."""


@dataclass(frozen=True, slots=True)
class CheckoutConfig:
    enabled: bool = False
    shop_id: str = ""
    card_id: str = ""
    callback_url: str = ""


@dataclass(frozen=True, slots=True)
class CheckoutOrder:
    id: str
    amount_rial: int
    status: str
    checkout: PaymentInitiation | None = None
