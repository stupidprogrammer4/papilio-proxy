from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TestGrantRepository(Protocol):
    async def grant(self, telegram_id: int, quota_bytes: int, duration_days: int) -> str: ...


@dataclass(slots=True)
class TestAccessService:
    repository: TestGrantRepository
    admin_ids: frozenset[int]

    async def grant(self, telegram_id: int, quota_mib: int, duration_days: int) -> str:
        if telegram_id not in self.admin_ids:
            raise PermissionError("Only a configured Telegram admin can receive a pilot")
        if not 1 <= quota_mib <= 1024 or not 1 <= duration_days <= 7:
            raise ValueError("Pilot must be 1–1024 MiB and 1–7 days")
        return await self.repository.grant(telegram_id, quota_mib * 1024**2, duration_days)
