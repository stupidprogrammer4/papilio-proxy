from datetime import UTC, datetime

from papilio.errors.exceptions import ConflictException, NotFoundException

from src.config.pagination import ServicePage
from src.config.settings import PapilioSettings
from src.modules.accounts.customer_portal.domain.dtos import (
    CustomerPage,
    CustomerPurchase,
    CustomerTopupCreate,
)
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.billing.wallet.domain.dtos import TopupCreate, TopupSearch
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.billing.wallet.interfaces import IWalletCommand
from src.modules.bot.domain.results import BotDelivery
from src.modules.network.configurations.interfaces import IProfileCommand
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.subscriptions.domain.dtos import (
    SubscriptionCreate,
    SubscriptionSearch,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand


class CustomerAccountCommand:
    def __init__(
        self,
        wallets: IWalletCommand,
        subscriptions: ISubscriptionCommand,
        profiles: IProfileCommand,
        preferences: IPreferencesService,
        settings: PapilioSettings,
        customers: ICustomerService,
    ) -> None:
        self.customers = customers
        self.wallets = wallets
        self.subscriptions = subscriptions
        self.profiles = profiles
        self.preferences = preferences
        self.settings = settings

    async def request_topup(
        self, customer_id: int, data: CustomerTopupCreate
    ) -> TopupModel:
        result = await self.wallets.request_topup(
            TopupCreate(
                customer_id=customer_id,
                amount_rial=data.amount_rial,
                destination_id=data.destination_id,
                request_key=f"customer:{customer_id}:{data.request_key}",
            )
        )
        return result

    async def topup(self, customer_id: int, id: int) -> TopupModel:
        result = await self.wallets.get_topup(id)
        if result.customer_id != customer_id:
            raise _missing("topup", id)
        return result

    async def topups(
        self, customer_id: int, data: CustomerPage
    ) -> ServicePage[TopupModel]:
        result = await self.wallets.search(
            TopupSearch(customer_id=customer_id, **data.model_dump())
        )
        return result

    async def purchase(
        self, customer_id: int, data: CustomerPurchase
    ) -> SubscriptionModel:
        result = await self.subscriptions.purchase(
            SubscriptionCreate(
                customer_id=customer_id,
                plan_id=data.plan_id,
                expected_price_rial=data.expected_price_rial,
                auto_renew=data.auto_renew,
                purchase_key=f"customer:{customer_id}:{data.purchase_key}",
            )
        )
        return result

    async def subscription(
        self, customer_id: int, id: int
    ) -> SubscriptionModel:
        result = await self.subscriptions.get(id)
        if result.customer_id != customer_id:
            raise _missing("subscription", id)
        return result

    async def subscriptions_page(
        self, customer_id: int, data: CustomerPage
    ) -> ServicePage[SubscriptionModel]:
        result = await self.subscriptions.search(
            SubscriptionSearch(customer_id=customer_id, **data.model_dump())
        )
        return result

    async def delivery(
        self, customer_id: int, id: int, rotate: bool
    ) -> BotDelivery:
        subscription = await self.subscription(customer_id, id)
        preferences = (await self.preferences.current()).values
        customer = await self.customers.get(customer_id)
        available = CustomerAccessPolicy.services_available(customer)
        ready = (
            available
            and subscription.status == "active"
            and (
                subscription.expires_at is None
                or subscription.expires_at
                > datetime.now(UTC).replace(tzinfo=None)
            )
            and (
                subscription.quota_bytes is None
                or subscription.used_bytes < subscription.quota_bytes
            )
        )
        if rotate and not preferences.customer_link_rotation:
            raise ConflictException(
                message="تغییر لینک توسط مشتری غیرفعال است.",
                message_code="customer_link_rotation_disabled",
                unique_dict={"id": id},
            )
        feed = (
            await self.profiles.subscription_url(id, rotate) if ready else None
        )
        token = None if feed is None else feed.rsplit("/", 1)[-1]
        origin = self.settings.public.customer_portal_origin.rstrip("/")
        return BotDelivery(
            entitlement_kind=subscription.entitlement_kind,
            subscription_id=id,
            status=subscription.status if available else "customer_hold",
            auto_renew=subscription.auto_renew,
            feed_url=feed,
            portal_url=None if token is None else f"{origin}/service/{token}",
            can_rotate_link=bool(preferences.customer_link_rotation) and ready,
        )


def _missing(entity: str, id: int) -> NotFoundException:
    return NotFoundException(
        message="رکورد پیدا نشد.",
        message_code=f"{entity}_not_found",
        entity=entity,
        identifier="id",
        identifier_value=id,
    )
