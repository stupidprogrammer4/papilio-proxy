from dataclasses import dataclass

from src.modules.sales.loyalty.domain.results import CustomerPriceQuote


@dataclass(frozen=True, slots=True)
class CustomerHoldCandidate:
    subscription_id: int
    customer_id: int


@dataclass(frozen=True, slots=True)
class SubscriptionRenewalQuote:
    available: bool
    payer_customer_id: int
    price_rial: int
    commerce: CustomerPriceQuote | None = None


@dataclass(frozen=True, slots=True)
class SubscriptionUsageUpdate:
    subscription_id: int
    used_bytes: int
