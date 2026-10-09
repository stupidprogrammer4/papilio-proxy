from src.config.settings import PapilioSettings
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.catalog.domain.policies import FulfillmentPolicy
from src.modules.sales.catalog.infra.mysql import PlanRepository
from src.modules.sales.loyalty.domain.results import CustomerPriceQuote
from src.modules.sales.loyalty.interfaces import ICustomerLoyaltyQuery
from src.modules.sales.reseller_billing.interfaces import IResellerBillingQuery
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.domain.results import (
    SubscriptionRenewalQuote,
)


class SubscriptionRenewalQuoteQuery:
    def __init__(
        self,
        plans: PlanRepository,
        reseller_billing: IResellerBillingQuery,
        preferences: IPreferencesService,
        settings: PapilioSettings,
        loyalty: ICustomerLoyaltyQuery,
    ) -> None:
        self.plans = plans
        self.reseller_billing = reseller_billing
        self.preferences = preferences
        self.settings = settings
        self.loyalty = loyalty

    async def get(
        self, subscription: SubscriptionModel, *, locked: bool = False
    ) -> SubscriptionRenewalQuote:
        payer_id = subscription.payer_customer_id or subscription.customer_id
        if subscription.entitlement_kind == "trial":
            return SubscriptionRenewalQuote(
                False, payer_id, subscription.price_rial
            )
        billing = await self.reseller_billing.renewal(subscription)
        if billing is not None:
            return SubscriptionRenewalQuote(
                billing.available, payer_id, billing.price_rial
            )
        fulfillment = (
            FulfillmentPolicy.model_validate_json(
                subscription.fulfillment_json
            )
            if subscription.fulfillment_json is not None
            else (await self.preferences.current()).values.fulfillment
            or self.settings.fulfillment.policy
        )
        price = subscription.price_rial
        commerce = None
        if subscription.commerce_json is not None:
            snapshot = CustomerPriceQuote.model_validate_json(
                subscription.commerce_json
            )
            price = snapshot.renewal_price_rial
            commerce = snapshot.model_copy(
                update={
                    "price_rial": price,
                    "discount_rial": snapshot.base_price_rial - price,
                    "first_purchase_discount_bps": 0,
                }
            )
        if fulfillment.renewal_price == "current_plan":
            plan = (
                await self.plans.locked(subscription.plan_id)
                if locked
                else await self.plans.get_by_id(subscription.plan_id)
            )
            if plan is None or not plan.is_active:
                return SubscriptionRenewalQuote(False, payer_id, price)
            commerce = await self.loyalty.quote(
                subscription.customer_id, plan.id, renewal=True, locked=locked
            )
            price = commerce.price_rial
        return SubscriptionRenewalQuote(True, payer_id, price, commerce)
