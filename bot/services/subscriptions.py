from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from bot.models import (
    Plan,
    Protocol,
    Subscription,
    SubscriptionStatus,
    TelegramUser,
    UnknownPlanError,
)


class SubscriptionRepository(ABC):
    @abstractmethod
    async def upsert_user(self, user: TelegramUser) -> None: ...

    @abstractmethod
    async def list_for_user(self, telegram_id: int) -> list[Subscription]: ...

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


@dataclass(slots=True)
class SubscriptionService:
    repository: SubscriptionRepository

    plans: PlanRepository

    async def register_user(self, user: TelegramUser) -> None:
        await self.repository.upsert_user(user)

    async def list_plans(self, *, active_only: bool = True) -> list[Plan]:
        return await self.plans.list(active_only=active_only)

    async def get_plan(self, code: str) -> Plan:
        plan = await self.plans.get(code)
        if plan is None:
            raise UnknownPlanError(code)
        return plan

    async def list_subscriptions(self, telegram_id: int) -> list[Subscription]:
        return await self.repository.list_for_user(telegram_id)

    async def create_order(
        self, telegram_id: int, plan_code: str, protocol: Protocol
    ) -> Subscription:
        plan = await self.get_plan(plan_code)
        if not plan.is_active:
            raise UnknownPlanError(plan_code)
        record = Subscription(
            id=str(uuid4()),
            telegram_id=telegram_id,
            plan_code=plan.code,
            protocol=protocol,
            status=SubscriptionStatus.PENDING_PAYMENT,
            price_rial=plan.price_rial,
            traffic_limit_bytes=plan.traffic_bytes,
            traffic_used_bytes=0,
            expires_at=None,
            created_at=datetime.now(UTC),
        )
        await self.repository.create(record)
        return record
