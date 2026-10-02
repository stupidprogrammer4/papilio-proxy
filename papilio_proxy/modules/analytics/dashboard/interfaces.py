from abc import ABC, abstractmethod

from papilio_proxy.modules.analytics.dashboard.domain.entities import DashboardSnapshot


class DashboardRepository(ABC):
    @abstractmethod
    async def snapshot(self) -> DashboardSnapshot: ...
