from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit, urlunsplit

from papilio.errors.exceptions import (
    ConflictException,
    NotFoundException,
    UnAuthorizedException,
)
from papilio.schemas.results import PagedType

from src.config.pagination import page_size
from src.config.settings import PapilioSettings
from src.modules.accounts.customer_auth.domain.results import CustomerLoginLink
from src.modules.accounts.customer_auth.interfaces import ICustomerAuthCommand
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.billing.wallet.domain.dtos import TopupCreate
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.billing.wallet.interfaces import IWalletCommand
from src.modules.bot.domain.dtos import (
    BotAutoRenew,
    BotIdentity,
    BotPurchase,
    BotTopup,
)
from src.modules.bot.domain.results import (
    BotDelivery,
    BotHome,
    BotSupportAccess,
)
from src.modules.network.configurations.interfaces import IProfileCommand
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.attention.domain.renewal import (
    CustomerRenewalEligibility,
)
from src.modules.sales.attention.interfaces import (
    ICustomerRenewalEligibilityQuery,
)
from src.modules.sales.catalog.domain.dtos import PlanSearch
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.catalog.interfaces import IPlanService
from src.modules.sales.loyalty.domain.results import (
    CustomerPriceQuote,
    CustomerTierRead,
)
from src.modules.sales.loyalty.interfaces import ICustomerLoyaltyQuery
from src.modules.sales.reseller_billing.interfaces import ICustomerCatalogQuery
from src.modules.sales.subscriptions.domain.dtos import (
    AutoRenewChoice,
    SubscriptionCreate,
    SubscriptionSearch,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand


class BotCommand:
    def __init__(
        self,
        customers: ICustomerService,
        customer_auth: ICustomerAuthCommand,
        wallets: IWalletCommand,
        plans: IPlanService,
        subscriptions: ISubscriptionCommand,
        settings: PapilioSettings,
        preferences: IPreferencesService,
        profiles: IProfileCommand,
        customer_catalog: ICustomerCatalogQuery,
        loyalty: ICustomerLoyaltyQuery,
        renewal_eligibility: ICustomerRenewalEligibilityQuery,
    ) -> None:
        self.customers = customers
        self.customer_auth = customer_auth
        self.wallets = wallets
        self.plans = plans
        self.subscriptions = subscriptions
        self.settings = settings
        self.preferences = preferences
        self.profiles = profiles
        self.customer_catalog = customer_catalog
        self.loyalty = loyalty
        self.renewal_eligibility = renewal_eligibility

    async def renewal_status(
        self, data: BotIdentity, subscription_id: int
    ) -> CustomerRenewalEligibility:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.renewal_eligibility.get(
            subscription_id, customer.id
        )
        return result

    @property
    def page_size(self) -> int:
        return page_size(self.settings, self.settings.operations.bot_page_size)

    async def home(self, data: BotIdentity) -> BotHome:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        balance = await self.wallets.balance(customer.id)
        preferences = (await self.preferences.current()).values
        return BotHome(
            preferences.brand_title,
            customer.id,
            customer.display_name,
            balance,
            preferences.payment_instructions,
            preferences.support_handle,
            tuple(preferences.topup_options_rial),
        )

    async def delivery(
        self, id: int, data: BotIdentity, rotate: bool = False
    ) -> BotDelivery:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        subscription = await self.subscriptions.get(id)
        if subscription.customer_id != customer.id:
            raise NotFoundException(
                message="اشتراک پیدا نشد.",
                message_code="subscription_not_found",
                entity="subscription",
                identifier="id",
                identifier_value=id,
            )
        preferences = (await self.preferences.current()).values
        can_rotate = bool(preferences.customer_link_rotation)
        if rotate and not can_rotate:
            raise ConflictException(
                message="تغییر لینک توسط مشتری غیرفعال است.",
                message_code="customer_link_rotation_disabled",
                unique_dict={"id": id},
            )
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
        feed_url = (
            await self.profiles.subscription_url(id, rotate) if ready else None
        )
        token = feed_url.rsplit("/", 1)[-1] if feed_url is not None else None
        return BotDelivery(
            entitlement_kind=subscription.entitlement_kind,
            subscription_id=id,
            status=subscription.status if available else "customer_hold",
            auto_renew=subscription.auto_renew,
            feed_url=feed_url,
            portal_url=f"{self.settings.public.customer_portal_origin.rstrip('/')}/service/{token}"
            if token is not None
            else None,
            can_rotate_link=can_rotate and ready,
        )

    async def active_plans(self, page: int) -> PagedType[PlanModel]:
        result = await self.plans.search(
            PlanSearch(active=True, page=page, per_page=self.page_size)
        )
        return result

    async def customer_plans(
        self, data: BotIdentity, page: int
    ) -> PagedType[PlanModel]:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.customer_catalog.search(
            customer.id, PlanSearch(page=page, per_page=self.page_size)
        )
        return result

    async def customer_plan(self, data: BotIdentity, id: int) -> PlanModel:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.customer_catalog.get(customer.id, id)
        quote = await self.loyalty.quote(customer.id, id)
        return result.model_copy(update={"price_rial": quote.price_rial})

    async def loyalty_status(self, data: BotIdentity) -> CustomerTierRead:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.loyalty.status(customer.id)
        return result

    async def price_quote(
        self, data: BotIdentity, plan_id: int
    ) -> CustomerPriceQuote:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.loyalty.quote(customer.id, plan_id)
        return result

    async def my_subscriptions(
        self, data: BotIdentity, page: int
    ) -> PagedType[SubscriptionModel]:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.subscriptions.search(
            SubscriptionSearch(
                customer_id=customer.id,
                page=page,
                per_page=self.page_size,
            )
        )
        return result

    async def request_topup(self, data: BotTopup) -> TopupModel:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.wallets.request_topup(
            TopupCreate(
                customer_id=customer.id,
                amount_rial=data.amount_rial,
                destination_id=data.destination_id,
                request_key=None
                if data.request_key is None
                else f"bot:{customer.id}:{data.request_key}",
            )
        )
        return result

    async def purchase(self, data: BotPurchase) -> SubscriptionModel:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.subscriptions.purchase(
            SubscriptionCreate(
                customer_id=customer.id,
                plan_id=data.plan_id,
                expected_price_rial=data.expected_price_rial,
                auto_renew=data.auto_renew,
                purchase_key=data.purchase_key,
            )
        )
        return result

    async def set_auto_renew(
        self, id: int, data: BotAutoRenew
    ) -> SubscriptionModel:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.subscriptions.customer_set_auto_renew(
            id, customer.id, AutoRenewChoice(enabled=data.enabled)
        )
        return result

    async def account_link(self, data: BotIdentity) -> CustomerLoginLink:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.customer_auth.issue_link(customer.id)
        return result

    async def plan(self, id: int) -> PlanModel:
        result = await self.plans.get_active(id)
        return result

    async def support_link(self, data: BotIdentity) -> BotSupportAccess:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        preferences = await self.preferences.current()
        handle = preferences.values.support_handle
        try:
            link = await self.customer_auth.issue_link(customer.id)
        except UnAuthorizedException:
            return BotSupportAccess(
                status="contact" if handle else "unavailable",
                url=None,
                expires_at=None,
                support_handle=handle,
            )
        parts = urlsplit(link.url)
        link.url = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode({"section": "support"}),
                parts.fragment,
            )
        )
        return BotSupportAccess(
            status="portal",
            url=link.url,
            expires_at=link.expires_at,
            support_handle=handle,
        )
