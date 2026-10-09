from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.app.policies import missing
from src.modules.accounts.resellers.domain.dtos import ResellerSearch
from src.modules.accounts.resellers.interfaces import IResellerRegistryQuery
from src.modules.sales.reseller_catalog.app.pricing import AgreementPricing
from src.modules.sales.reseller_catalog.domain.dtos import AgreementPrice
from src.modules.sales.reseller_catalog.domain.models import (
    ResellerPlanChangeModel,
)
from src.modules.sales.reseller_catalog.domain.results import (
    ResellerPlanFacts,
    ResellerPlanQuote,
)
from src.modules.sales.reseller_catalog.infra.mysql import (
    ResellerPlanChangeRepository,
)
from src.modules.sales.reseller_catalog.infra.readers import ResellerPlanReader
from src.modules.sales.reseller_catalog.interfaces import IResellerPlanQuery


class ResellerPlanQuery:
    def __init__(
        self,
        reader: ResellerPlanReader,
        resellers: IResellerRegistryQuery,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.resellers = resellers
        self.settings = settings

    @staticmethod
    def quoted(facts: ResellerPlanFacts) -> ResellerPlanQuote:
        return ResellerPlanQuote(
            facts,
            AgreementPricing.quote(
                AgreementPrice.model_validate_json(facts.agreement.price_json),
                facts.plan.price_rial,
            ),
        )

    async def get(self, reseller_id: int, id: int) -> ResellerPlanQuote:
        facts = await self.reader.owned(reseller_id, id)
        if facts is None:
            raise missing("reseller_plan", id)
        return self.quoted(facts)

    async def search(
        self, reseller_id: int, data: ResellerSearch
    ) -> ServicePage[ResellerPlanQuote]:
        await self.resellers.get(reseller_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            reseller_id, data.q, None, None, (data.page - 1) * limit, limit
        )
        return ServicePage(
            [self.quoted(facts) for facts in result.items],
            result.total_items,
            limit,
        )

    async def offered(
        self, reseller_id: int, data: ResellerSearch
    ) -> ServicePage[ResellerPlanQuote]:
        await self.resellers.get(reseller_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            reseller_id, data.q, True, True, (data.page - 1) * limit, limit
        )
        return ServicePage(
            [self.quoted(facts) for facts in result.items],
            result.total_items,
            limit,
        )


class ResellerPlanHistoryQuery:
    def __init__(
        self,
        repo: ResellerPlanChangeRepository,
        agreements: IResellerPlanQuery,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.agreements = agreements
        self.settings = settings

    async def search(
        self, reseller_id: int, id: int, data: ResellerSearch
    ) -> ServicePage[ResellerPlanChangeModel]:
        await self.agreements.get(reseller_id, id)
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(id, (data.page - 1) * limit, limit)
        return service_page(result, limit)
