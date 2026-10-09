from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.accounts.customer_portal.domain.dtos import (
    CustomerPage,
    CustomerPurchase,
    CustomerTopupCreate,
)
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.bot.domain.results import BotDelivery
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


class ICustomerAccountCommand(Protocol):
    def request_topup(
        self, customer_id: int, data: CustomerTopupCreate
    ) -> Awaitable[TopupModel]: ...
    def topup(self, customer_id: int, id: int) -> Awaitable[TopupModel]: ...
    def topups(
        self, customer_id: int, data: CustomerPage
    ) -> Awaitable[ServicePage[TopupModel]]: ...
    def purchase(
        self, customer_id: int, data: CustomerPurchase
    ) -> Awaitable[SubscriptionModel]: ...
    def subscription(
        self, customer_id: int, id: int
    ) -> Awaitable[SubscriptionModel]: ...
    def subscriptions_page(
        self, customer_id: int, data: CustomerPage
    ) -> Awaitable[ServicePage[SubscriptionModel]]: ...
    def delivery(
        self, customer_id: int, id: int, rotate: bool
    ) -> Awaitable[BotDelivery]: ...
