from src.modules.network.node_capabilities.domain.models import (
    NodeCapabilityObservationModel,
)
from src.modules.network.node_capabilities.infra.mysql import (
    NodeCapabilityObservationRepository,
)


class NodeCapabilityService:
    def __init__(self, repo: NodeCapabilityObservationRepository) -> None:
        self.repo = repo

    async def find(
        self, node_id: int, report_id: str
    ) -> NodeCapabilityObservationModel | None:
        result = await self.repo.by_report(node_id, report_id)
        return result

    async def create(
        self, data: NodeCapabilityObservationModel
    ) -> NodeCapabilityObservationModel:
        result = await self.repo.create(data)
        return result
