import asyncio
import secrets

from papilio.errors.exceptions import NotFoundException, UnAuthorizedException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256, secure_compare

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.nodes.domain.dtos import (
    NodeCreate,
    NodeEnabled,
    NodeSearch,
)
from src.modules.network.nodes.domain.models import NodeModel
from src.modules.network.nodes.domain.results import RegisteredNode
from src.modules.network.nodes.infra.mysql import NodeRepository


class NodeService:
    def __init__(
        self, repo: NodeRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def authenticate(self, code: str, agent_key: str) -> NodeModel:
        node = await self.repo.by_code(code)
        digest = await asyncio.to_thread(hash_sha256, agent_key)
        if (
            node is None
            or not agent_key
            or not secure_compare(digest, node.agent_key_hash)
        ):
            raise UnAuthorizedException(
                message="دسترسی نود معتبر نیست.",
                message_code="node_unauthorized",
            )
        return node

    @handle_conflicts
    @transactional
    async def register(self, data: NodeCreate) -> RegisteredNode:
        token = secrets.token_urlsafe(32)
        node = await self.repo.create(
            NodeModel(
                **data.model_dump(),
                agent_key_hash=(await asyncio.to_thread(hash_sha256, token)),
                is_enabled=False,
            )
        )
        return RegisteredNode(node, token)

    @transactional
    async def set_enabled(self, id: int, data: NodeEnabled) -> NodeModel:
        node = await self.repo.get_by_id(id)
        if node is None:
            raise _missing(id)
        result = await self.repo.update_existing(node, data.enabled)
        return result

    async def get(self, id: int) -> NodeModel:
        node = await self.repo.get_by_id(id)
        if node is None:
            raise _missing(id)
        return node

    async def locked(self, id: int) -> NodeModel:
        node = await self.repo.locked(id)
        if node is None:
            raise _missing(id)
        return node

    async def search(self, data: NodeSearch) -> ServicePage[NodeModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page((data.page - 1) * limit, limit, data.q)
        return service_page(result, limit)


def _missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="نود پیدا نشد.",
        message_code="node_not_found",
        entity="node",
        identifier="id",
        identifier_value=id,
    )
