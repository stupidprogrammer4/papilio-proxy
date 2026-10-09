from papilio.errors.exceptions import NotFoundException

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.cores.domain.dtos import CoreSearch
from src.modules.network.cores.domain.results import CoreInventoryFacts
from src.modules.network.cores.infra.inventory import CoreInventoryReader
from src.modules.network.nodes.interfaces import INodeService


class CoreInventoryQuery:
    def __init__(
        self,
        reader: CoreInventoryReader,
        nodes: INodeService,
        settings: PapilioSettings,
    ) -> None:
        self.reader, self.nodes, self.settings = reader, nodes, settings

    async def detail(self, core_id: int) -> CoreInventoryFacts:
        result = await self.reader.detail(core_id)
        if result is None:
            raise NotFoundException(
                message="Core not found.",
                message_code="core_not_found",
                entity="core",
                identifier="id",
                identifier_value=core_id,
            )
        return result

    async def search(
        self, node_id: int, data: CoreSearch
    ) -> ServicePage[CoreInventoryFacts]:
        await self.nodes.get(node_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            node_id, data.q, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
