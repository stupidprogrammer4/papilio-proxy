from dataclasses import dataclass

from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.sales.attention.domain.models import (
    SubscriptionAttentionModel,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


@dataclass(frozen=True, slots=True)
class SubscriptionAttentionFacts:
    attention: SubscriptionAttentionModel
    subscription: SubscriptionModel
    customer: CustomerModel
