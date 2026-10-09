import asyncio
from datetime import UTC, datetime

from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.decorators import transactional
from sqlalchemy.exc import OperationalError

from src.config.settings import PapilioSettings
from src.modules.network.ip_limits.domain.purchased import PlanIpPolicyRead
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.checkout.app.errors import (
    checkout_conflict,
    offer_lock_busy,
)
from src.modules.sales.checkout.app.product_policy import CheckoutProductPolicy
from src.modules.sales.checkout.domain.contracts import (
    CheckoutCapacity,
    CheckoutOffer,
)
from src.modules.sales.checkout.infra.readers import CheckoutOfferReader
from src.modules.sales.checkout.interfaces import IPurchaseCheckoutPolicyQuery
from src.modules.sales.loyalty.interfaces import ICustomerLoyaltyQuery


class CheckoutOfferQuery:
    def __init__(
        self,
        reader: CheckoutOfferReader,
        quotes: ICustomerLoyaltyQuery,
        preferences: IPreferencesService,
        settings: PapilioSettings,
        capacity: CheckoutCapacity,
        policies: IPurchaseCheckoutPolicyQuery,
    ) -> None:
        self.reader, self.quotes, self.policies = reader, quotes, policies
        self.preferences, self.settings, self.capacity = (
            preferences,
            settings,
            capacity,
        )

    @transactional
    async def get(self, customer_id: int, plan_id: int) -> CheckoutOffer:
        facts = await self.reader.customer_plan_current(customer_id, plan_id)
        if facts is None:
            raise NotFoundException(
                message="Checkout offer not found",
                message_code="checkout_offer_not_found",
                entity="plan",
                identifier="id",
                identifier_value=plan_id,
            )
        if await self.reader.has_reseller_owner_current(customer_id):
            raise checkout_conflict(
                "checkout_reseller_funding_unsupported", plan_id
            )
        quote = await self.quotes.quote(customer_id, plan_id, locked=True)
        values = (await self.preferences.current(locked=True)).values
        policy = await self.policies.current(locked=True)
        try:
            facts = await self.reader.product_current(
                facts, self.capacity.max_offer_memberships + 1
            )
        except OperationalError as error:
            if offer_lock_busy(error):
                raise checkout_conflict(
                    "checkout_offer_busy", plan_id
                ) from None
            raise
        CheckoutProductPolicy.admit(facts, self.capacity, policy)
        computation = CheckoutProductPolicy.computation_input(
            facts,
            quote,
            values,
            self.settings,
        )
        fingerprint, ip_policy = await asyncio.to_thread(
            CheckoutProductPolicy.offer_terms, computation
        )
        return CheckoutOffer(
            effective_ip_policy=PlanIpPolicyRead(
                policy=ip_policy,
                source="plan_override"
                if computation.ip_limit_json
                else "current_defaults",
            ),
            customer_id=customer_id,
            plan_id=plan_id,
            price_rial=quote.price_rial,
            offer_sha256=fingerprint,
            plan_title=facts.plan.title,
            quota_bytes=facts.plan.quota_bytes,
            duration_days=facts.plan.duration_days,
            membership_count=len(facts.memberships),
            delivery_mode="manual_profiles"
            if facts.plan.group_id is None
            else "configured_bundle",
            default_expiry_seconds=policy.default_expiry_seconds,
            captured_at=datetime.now(UTC),
        )
