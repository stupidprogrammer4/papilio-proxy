from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.sales.loyalty.domain.results import (
    CustomerPriceQuote,
    CustomerTierRead,
)
from src.modules.sales.loyalty.infra.readers import (
    CustomerPurchaseVolumeReader,
)
from src.modules.sales.loyalty.interfaces import (
    ICustomerTierService,
    ILoyaltyPolicyService,
)
from src.modules.sales.reseller_billing.infra.readers import (
    ResellerBillingReader,
)
from src.modules.sales.reseller_billing.interfaces import ICustomerCatalogQuery


class CustomerLoyaltyQuery:
    def __init__(
        self,
        reader: CustomerPurchaseVolumeReader,
        tiers: ICustomerTierService,
        policies: ILoyaltyPolicyService,
        customers: ICustomerService,
        plans: ICustomerCatalogQuery,
        resellers: ResellerBillingReader,
        settings: PapilioSettings,
    ) -> None:
        self.reader, self.tiers, self.policies = reader, tiers, policies
        self.customers, self.plans, self.settings = customers, plans, settings
        self.resellers = resellers

    async def status(
        self, customer_id: int, *, locked: bool = False
    ) -> CustomerTierRead:
        await self.customers.get(customer_id)
        policy = await self.policies.current(locked=locked)
        facts = await self.reader.totals(
            customer_id,
            0,
            "paid",
            ["failed", "cancelled"],
            locked,
            policy.values.minimum_qualifying_rial,
        )
        candidates = await self.tiers.candidates(locked=locked)
        volume = max(
            facts.net_bytes
            if policy.values.tier_basis == "net_purchases"
            else facts.lifetime_bytes,
            0,
        )
        eligible = [
            tier
            for tier in candidates
            if tier.is_enabled and tier.minimum_bytes <= volume
        ]
        upcoming = [
            tier
            for tier in candidates
            if tier.is_enabled and tier.minimum_bytes > volume
        ]
        tier = max(
            eligible, key=lambda row: (row.minimum_bytes, row.id), default=None
        )
        next_tier = min(
            upcoming, key=lambda row: (row.minimum_bytes, row.id), default=None
        )
        return CustomerTierRead(
            customer_id=customer_id,
            purchased_bytes=volume,
            purchase_count=max(facts.purchase_count, 0)
            + facts.legacy_purchase_count,
            lifetime_purchase_count=facts.lifetime_purchase_count
            + facts.legacy_purchase_count,
            tier=tier,
            next_tier=next_tier,
        )

    async def quote(
        self,
        customer_id: int,
        plan_id: int,
        *,
        renewal: bool = False,
        locked: bool = False,
    ) -> CustomerPriceQuote:
        await self.customers.get(customer_id)
        plan = await self.plans.get(customer_id, plan_id)
        reseller = await self.resellers.owner(customer_id)
        policy = (
            await self.policies.current(locked=locked)
            if self.settings.loyalty is not None and reseller is None
            else None
        )
        if policy is None or not policy.values.enabled:
            return CustomerPriceQuote(
                customer_id=customer_id,
                plan_id=plan_id,
                base_price_rial=plan.price_rial,
                price_rial=plan.price_rial,
                discount_rial=0,
                renewal_price_rial=plan.price_rial,
                tier_code=None,
                tier_discount_bps=0,
                first_purchase_discount_bps=0,
                policy_revision=policy.revision if policy else 0,
            )
        status = await self.status(customer_id, locked=locked)
        values = policy.values
        tier_bps = (
            status.tier.discount_bps
            if values.enabled
            and status.tier is not None
            and (not renewal or values.renewal_tier_discount)
            else 0
        )
        first_bps = (
            values.first_purchase_discount_bps
            if values.enabled
            and not renewal
            and (
                status.purchase_count
                if values.first_purchase_basis == "net_purchases"
                else status.lifetime_purchase_count
            )
            == 0
            else 0
        )
        if values.combination_mode == "sequential":
            discount = min(
                plan.price_rial
                * (100000000 - (10000 - tier_bps) * (10000 - first_bps))
                // 100000000,
                plan.price_rial * values.maximum_discount_bps // 10000,
            )
        else:
            bps = (
                max(tier_bps, first_bps)
                if values.combination_mode == "best"
                else tier_bps + first_bps
            )
            discount = (
                plan.price_rial
                * min(bps, values.maximum_discount_bps)
                // 10000
            )
        return CustomerPriceQuote(
            customer_id=customer_id,
            plan_id=plan_id,
            base_price_rial=plan.price_rial,
            price_rial=plan.price_rial - discount,
            discount_rial=discount,
            renewal_price_rial=plan.price_rial
            - (
                plan.price_rial
                * min(tier_bps, values.maximum_discount_bps)
                // 10000
                if values.renewal_tier_discount
                else 0
            ),
            tier_code=status.tier.code if status.tier is not None else None,
            tier_discount_bps=tier_bps,
            first_purchase_discount_bps=first_bps,
            policy_revision=policy.revision,
        )
