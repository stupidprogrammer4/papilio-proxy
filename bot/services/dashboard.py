from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    users: int
    subscriptions: int
    active: int
    pending: int
    traffic_used: int
    traffic_limit: int
    recent_users: list[tuple[int, str, str | None, int]]
    subscriptions_rows: list[tuple[str, int, str, str, int, int]]


class DashboardRepository(ABC):
    @abstractmethod
    async def snapshot(self) -> DashboardSnapshot: ...


class DashboardService:
    def __init__(self, repository: DashboardRepository) -> None:
        self._repository = repository

    async def snapshot(self) -> DashboardSnapshot:
        return await self._repository.snapshot()
