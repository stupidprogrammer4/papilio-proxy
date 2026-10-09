from collections.abc import Awaitable
from typing import Protocol

from papilio.schemas.results import PagedType

from src.modules.accounts.customer_auth.domain.results import CustomerLoginLink
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.bot.domain.dtos import (
    BotAutoRenew,
    BotIdentity,
    BotPurchase,
    BotTopup,
    BotTrialClaim,
)
from src.modules.bot.domain.results import (
    BotDelivery,
    BotHome,
    BotSupportAccess,
)
from src.modules.sales.attention.domain.renewal import (
    CustomerRenewalEligibility,
)
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.loyalty.domain.results import (
    CustomerPriceQuote,
    CustomerTierRead,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.trials.domain.results import TrialAvailability


class IBotCommand(Protocol):
    def renewal_status(
        self, data: BotIdentity, subscription_id: int
    ) -> Awaitable[CustomerRenewalEligibility]: ...
    def loyalty_status(
        self, data: BotIdentity
    ) -> Awaitable[CustomerTierRead]: ...
    def price_quote(
        self, data: BotIdentity, plan_id: int
    ) -> Awaitable[CustomerPriceQuote]: ...
    def plan(self, id: int) -> Awaitable[PlanModel]: ...
    def support_link(
        self, data: BotIdentity
    ) -> Awaitable[BotSupportAccess]: ...
    def account_link(
        self, data: BotIdentity
    ) -> Awaitable[CustomerLoginLink]: ...
    def delivery(
        self, id: int, data: BotIdentity, rotate: bool = False
    ) -> Awaitable[BotDelivery]: ...
    @property
    def page_size(self) -> int: ...
    def home(self, data: BotIdentity) -> Awaitable[BotHome]: ...
    def active_plans(self, page: int) -> Awaitable[PagedType[PlanModel]]: ...
    def customer_plans(
        self, data: BotIdentity, page: int
    ) -> Awaitable[PagedType[PlanModel]]: ...
    def customer_plan(
        self, data: BotIdentity, id: int
    ) -> Awaitable[PlanModel]: ...
    def my_subscriptions(
        self, data: BotIdentity, page: int
    ) -> Awaitable[PagedType[SubscriptionModel]]: ...
    def request_topup(self, data: BotTopup) -> Awaitable[TopupModel]: ...
    def purchase(self, data: BotPurchase) -> Awaitable[SubscriptionModel]: ...
    def set_auto_renew(
        self, id: int, data: BotAutoRenew
    ) -> Awaitable[SubscriptionModel]: ...


class IBotTrialCommand(Protocol):
    def availability(
        self, data: BotIdentity
    ) -> Awaitable[TrialAvailability]: ...
    def claim(self, data: BotTrialClaim) -> Awaitable[SubscriptionModel]: ...
