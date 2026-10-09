from datetime import UTC, datetime

from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.attention.domain.renewal import (
    CustomerRenewalEligibility,
)
from src.modules.sales.attention.infra.readers import CustomerRenewalReader
from src.modules.sales.catalog.domain.policies import FulfillmentPolicy
from src.modules.sales.subscriptions.interfaces import (
    ISubscriptionRenewalQuoteQuery,
)


class CustomerRenewalEligibilityQuery:
    def __init__(
        self,
        reader: CustomerRenewalReader,
        quotes: ISubscriptionRenewalQuoteQuery,
        preferences: IPreferencesService,
        settings: PapilioSettings,
    ) -> None:
        (
            self.reader,
            self.quotes,
            self.preferences,
            self.settings,
        ) = reader, quotes, preferences, settings

    @transactional
    async def get(
        self, subscription_id: int, customer_id: int
    ) -> CustomerRenewalEligibility:
        facts = await self.reader.owned_current(subscription_id, customer_id)
        if facts is None:
            raise NotFoundException(
                message="Subscription not found",
                message_code="subscription_not_found",
                entity="subscription",
                identifier="id",
                identifier_value=subscription_id,
            )
        subscription, customer, payer = (
            facts.subscription,
            facts.customer,
            facts.payer,
        )
        payer_id = subscription.payer_customer_id or customer_id
        quote = await self.quotes.get(subscription, locked=True)
        fulfillment = (
            FulfillmentPolicy.model_validate_json(
                subscription.fulfillment_json
            )
            if subscription.fulfillment_json is not None
            else (await self.preferences.current()).values.fulfillment
            or self.settings.fulfillment.policy
        )
        now = datetime.now(UTC)
        due = (
            subscription.expires_at is not None
            and subscription.expires_at <= now.replace(tzinfo=None)
            and fulfillment.renewal_trigger in {"expiry", "either"}
        ) or (
            subscription.quota_bytes is not None
            and subscription.used_bytes >= subscription.quota_bytes
            and fulfillment.renewal_trigger in {"quota", "either"}
        )
        reason = None
        if subscription.entitlement_kind == "trial":
            reason = "trial_not_renewable"
        elif subscription.status not in {"active", "expired", "exhausted"}:
            reason = "subscription_not_renewable"
        elif (
            customer is None
            or not customer.is_active
            or not CustomerAccessPolicy.renewals_available(customer)
        ):
            reason = "customer_renewals_disabled"
        elif (
            payer is None
            or not payer.is_active
            or not CustomerAccessPolicy.renewals_available(payer)
        ):
            reason = "payer_renewals_disabled"
        elif not quote.available:
            reason = "renewal_quote_unavailable"
        balance = (
            await self.reader.own_wallet_balance_current(customer_id)
            if payer_id == customer_id
            else None
        )
        price = quote.price_rial if quote.available else None
        funded = (
            balance >= price
            if balance is not None and price is not None
            else None
        )
        return CustomerRenewalEligibility(
            subscription_id=subscription.id,
            renewal_generation=subscription.renewal_count,
            checked_at=now,
            auto_renew=subscription.auto_renew,
            quote_available=quote.available,
            eligible=reason is None,
            reason_code=reason,
            renewal_due=due,
            auto_renew_authorized=reason is None and subscription.auto_renew,
            wallet_funded=funded,
            payer_kind="self" if payer_id == customer_id else "other",
            wallet_balance_rial=balance,
            renewal_price_rial=price,
            wallet_shortfall_rial=max(0, price - balance)
            if price is not None and balance is not None
            else None,
        )
