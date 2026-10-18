from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.billing.wallet.infra.mysql import TopupRepository


class TopupRecordService:
    def __init__(self, repo: TopupRepository) -> None:
        self.repo = repo

    async def get(self, id: int) -> TopupModel | None:
        result = await self.repo.get_by_id(id)
        return result

    async def locked(self, id: int) -> TopupModel | None:
        result = await self.repo.locked(id)
        return result
