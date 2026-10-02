from abc import ABC, abstractmethod

from papilio_proxy.modules.sales.subscriptions.domain.entities import (
    Plan,
    Subscription,
    SubscriptionStatus,
    TelegramUser,
)


class SubscriptionRepository(ABC):
    @abstractmethod
    async def upsert_user(self, user: TelegramUser) -> None: ...

    @abstractmethod
    async def list_for_user(
        self,
        telegram_id: int,
        *,
        statuses: frozenset[SubscriptionStatus] | None = None,
    ) -> list[Subscription]: ...

    @abstractmethod
    async def create(self, subscription: Subscription) -> None: ...


class PlanRepository(ABC):
    @abstractmethod
    async def list(self, *, active_only: bool = True) -> list[Plan]: ...

    @abstractmethod
    async def get(self, code: str) -> Plan | None: ...

    @abstractmethod
    async def save(self, plan: Plan) -> None: ...

    @abstractmethod
    async def set_active(self, code: str, is_active: bool) -> None: ...
    @abstractmethod
    async def delete(self, code: str) -> None: ...
