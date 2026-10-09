from src.config.pagination import ServicePage, page_size
from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.app.policies import (
    ResellerCapacity,
    conflict,
)
from src.modules.accounts.resellers.domain.dtos import ResellerPolicy
from src.modules.sales.catalog.domain.dtos import PlanSearch
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.catalog.interfaces import IPlanService
from src.modules.sales.reseller_billing.infra.readers import (
    ResellerBillingReader,
)
from src.modules.sales.reseller_catalog.app.pricing import AgreementPricing
from src.modules.sales.reseller_catalog.domain.dtos import AgreementPrice
from src.modules.sales.reseller_catalog.domain.results import ResellerPlanFacts
from src.modules.sales.reseller_catalog.infra.readers import ResellerPlanReader


class CustomerCatalogQuery:
    def __init__(
        self,
        reader: ResellerBillingReader,
        agreements: ResellerPlanReader,
        plans: IPlanService,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.agreements = agreements
        self.plans = plans
        self.settings = settings

    @staticmethod
    def priced(facts: ResellerPlanFacts) -> PlanModel:
        changes = PlanModel.patch(
            price_rial=AgreementPricing.quote(
                AgreementPrice.model_validate_json(facts.agreement.price_json),
                facts.plan.price_rial,
            )
        )
        return facts.plan.model_copy(
            update=changes.model_dump(exclude_unset=True)
        )

    def eligible(self, policy: ResellerPolicy) -> bool:
        capacity = self.settings.resellers
        return (
            capacity is not None
            and capacity.enabled
            and ResellerCapacity.valid(policy, capacity)
            and policy.customer_self_purchase
            and policy.payer_mode in {"customer_wallet", "either"}
        )

    async def search(
        self, customer_id: int, data: PlanSearch
    ) -> ServicePage[PlanModel]:
        reseller = await self.reader.owner(customer_id)
        if reseller is None:
            result = await self.plans.search(
                PlanSearch(
                    q=data.q,
                    active=True,
                    page=data.page,
                    per_page=data.per_page,
                )
            )
            return result
        limit = page_size(self.settings, data.per_page)
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        if not reseller.sales_enabled or not self.eligible(policy):
            return ServicePage([], 0, limit)
        facts = await self.agreements.page(
            reseller.id, data.q, True, True, (data.page - 1) * limit, limit
        )
        return ServicePage(
            [self.priced(row) for row in facts.items], facts.total_items, limit
        )

    async def get(self, customer_id: int, plan_id: int) -> PlanModel:
        reseller = await self.reader.owner(customer_id)
        if reseller is None:
            result = await self.plans.get_active(plan_id)
            return result
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        if not reseller.sales_enabled or not self.eligible(policy):
            raise conflict("reseller_customer_purchase_disabled")
        facts = await self.agreements.for_plan(reseller.id, plan_id)
        if (
            facts is None
            or not facts.agreement.enabled
            or not facts.plan.is_active
        ):
            raise conflict("reseller_plan_unavailable")
        return self.priced(facts)
