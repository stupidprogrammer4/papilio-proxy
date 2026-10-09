from collections.abc import Awaitable
from datetime import datetime
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.sales.attention.domain.dtos import SubscriptionAttentionSearch
from src.modules.sales.attention.domain.models import (
    SubscriptionAttentionModel,
)
from src.modules.sales.attention.domain.renewal import (
    CustomerRenewalEligibility,
)
from src.modules.sales.attention.domain.results import (
    SubscriptionAttentionFacts,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.domain.results import (
    SubscriptionRenewalQuote,
)


class ISubscriptionAttentionCommand(Protocol):
    def check(
        self, subscription_id: int
    ) -> Awaitable[SubscriptionAttentionModel]: ...


class ISubscriptionAttentionQuery(Protocol):
    def due_ids(self) -> Awaitable[list[int]]: ...
    def search(
        self, data: SubscriptionAttentionSearch
    ) -> Awaitable[ServicePage[SubscriptionAttentionFacts]]: ...


class ISubscriptionAlertCommand(Protocol):
    def publish(
        self,
        subscription: SubscriptionModel,
        quote: SubscriptionRenewalQuote,
        now: datetime,
    ) -> Awaitable[bool]: ...


class ICustomerRenewalEligibilityQuery(Protocol):
    def get(
        self, subscription_id: int, customer_id: int
    ) -> Awaitable[CustomerRenewalEligibility]: ...
