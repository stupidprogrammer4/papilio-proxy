from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.cores.app.protocols import CoreProtocols
from src.modules.network.cores.domain.dtos import CoreCreate, CoreSearch
from src.modules.network.cores.domain.models import CoreModel
from src.modules.network.cores.infra.mysql import CoreRepository
from src.modules.network.nodes.interfaces import INodeService


class CoreService:
    @staticmethod
    def supported_protocols(kind: str) -> tuple[str, ...]:
        return CoreProtocols.supported(kind)

    def __init__(
        self,
        repo: CoreRepository,
        nodes: INodeService,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.nodes = nodes
        self.settings = settings

    @handle_conflicts
    @transactional
    async def create(self, node_id: int, data: CoreCreate) -> CoreModel:
        await self.nodes.get(node_id)
        result = await self.repo.create(
            CoreModel(node_id=node_id, **data.model_dump())
        )
        return result

    @handle_conflicts
    @transactional
    async def default(self, node_id: int, protocol: str) -> CoreModel:
        await self.nodes.get(node_id)
        kind = (
            "openvpn"
            if protocol == "openvpn"
            else "wireguard"
            if protocol == "wireguard"
            else "hysteria"
            if protocol == "hysteria2"
            else "xray"
        )
        code = "default_" + kind
        result = await self.repo.reserve_default(
            CoreModel(node_id=node_id, code=code, label=kind, kind=kind)
        )
        return result

    async def get(self, id: int) -> CoreModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise NotFoundException(
                message="هسته پیدا نشد.",
                message_code="core_not_found",
                entity="core",
                identifier="id",
                identifier_value=id,
            )
        return result

    async def search(
        self, node_id: int, data: CoreSearch
    ) -> ServicePage[CoreModel]:
        await self.nodes.get(node_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            node_id, data.q, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
