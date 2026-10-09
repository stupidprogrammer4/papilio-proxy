import asyncio

from papilio.infra.db.tools.decorators import transactional
from sqlalchemy.exc import OperationalError

from src.config.settings import PapilioSettings
from src.modules.operations.preferences.domain.dtos import BusinessPreferences
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.checkout.app.errors import (
    checkout_conflict,
    checkout_missing,
    offer_lock_busy,
)
from src.modules.sales.checkout.app.product_policy import CheckoutProductPolicy
from src.modules.sales.checkout.domain.contracts import CheckoutCapacity
from src.modules.sales.checkout.infra.readers import CheckoutOfferReader
from src.modules.sales.checkout.interfaces import IPurchaseCheckoutPolicyQuery
from src.modules.sales.loyalty.domain.results import CustomerPriceQuote


class CheckoutProductVerifier:
    """Before-debit product verification without recursion or a new quote.

    The subscription owner supplies its locked plan, actual price quote and
    current-read purchased policy defaults. No public input supplies defaults.
    """

    def __init__(
        self,
        reader: CheckoutOfferReader,
        settings: PapilioSettings,
        capacity: CheckoutCapacity,
        policies: IPurchaseCheckoutPolicyQuery,
    ) -> None:
        self.reader, self.settings, self.capacity = reader, settings, capacity
        self.policies = policies

    @transactional
    async def verify(
        self,
        customer_id: int,
        plan: PlanModel,
        quote: CustomerPriceQuote,
        values: BusinessPreferences,
        expected_sha256: str,
    ) -> None:
        if quote.customer_id != customer_id or quote.plan_id != plan.id:
            raise checkout_conflict(
                "checkout_quote_identity_conflict", plan.id
            )
        try:
            facts = await self.reader.current(
                customer_id, plan.id, self.capacity.max_offer_memberships + 1
            )
        except OperationalError as error:
            if offer_lock_busy(error):
                raise checkout_conflict(
                    "checkout_offer_busy", plan.id
                ) from None
            raise
        if facts is None:
            raise checkout_missing(plan.id)
        if await self.reader.has_reseller_owner_current(customer_id):
            raise checkout_conflict(
                "checkout_reseller_funding_unsupported", plan.id
            )
        CheckoutProductPolicy.admit(
            facts, self.capacity, await self.policies.current(locked=True)
        )
        computation = CheckoutProductPolicy.computation_input(
            facts,
            quote,
            values,
            self.settings,
        )
        actual = await asyncio.to_thread(
            CheckoutProductPolicy.fingerprint, computation
        )
        if actual != expected_sha256:
            raise checkout_conflict("checkout_offer_changed", plan.id)
