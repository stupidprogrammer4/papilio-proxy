from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


class CustomerRenewalEligibility(BaseModel):
    subscription_id: int
    renewal_generation: int
    checked_at: datetime
    auto_renew: bool
    quote_available: bool
    eligible: bool
    reason_code: str | None
    renewal_due: bool
    auto_renew_authorized: bool
    wallet_funded: bool | None
    payer_kind: Literal["self", "other", "none"]
    wallet_balance_rial: int | None
    renewal_price_rial: int | None
    wallet_shortfall_rial: int | None


@dataclass(frozen=True, slots=True)
class CustomerRenewalFacts:
    subscription: SubscriptionModel
    customer: CustomerModel | None
    payer: CustomerModel | None
