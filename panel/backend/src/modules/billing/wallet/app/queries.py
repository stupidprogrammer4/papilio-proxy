from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.billing.wallet.domain.dtos import WalletLedgerSearch
from src.modules.billing.wallet.domain.results import WalletLedgerFacts
from src.modules.billing.wallet.infra.readers import WalletLedgerReader


class WalletLedgerQuery:
    def __init__(
        self,
        customers: ICustomerService,
        reader: WalletLedgerReader,
        settings: PapilioSettings,
    ) -> None:
        self.customers = customers
        self.reader = reader
        self.settings = settings

    async def search(
        self, customer_id: int, data: WalletLedgerSearch
    ) -> ServicePage[WalletLedgerFacts]:
        await self.customers.get(customer_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            customer_id, data.reason, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
