from __future__ import annotations

from papilio_proxy.modules.analytics.dashboard.domain.entities import DashboardSnapshot
from papilio_proxy.modules.analytics.dashboard.interfaces import DashboardRepository


class DashboardService:
    def __init__(self, repository: DashboardRepository) -> None:
        self._repository = repository

    async def snapshot(self) -> DashboardSnapshot:
        return await self._repository.snapshot()
