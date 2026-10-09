from src.modules.network.ip_limits.domain.models import IpLeaseStateModel
from src.modules.network.ip_limits.infra.leases import IpLeaseStateRepository


class IpLeaseTrackingService:
    def __init__(self, repo: IpLeaseStateRepository) -> None:
        self.repo = repo

    async def initialize_purchase(self, subscription_id: int) -> None:
        await self.repo.create(
            IpLeaseStateModel(
                subscription_id=subscription_id, history_complete=True
            )
        )
