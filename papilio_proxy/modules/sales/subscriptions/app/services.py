from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from papilio_proxy.modules.sales.subscriptions.domain.entities import (
    Plan,
    Protocol,
    Subscription,
    SubscriptionStatus,
    TelegramUser,
    UnknownPlanError,
)
from papilio_proxy.modules.sales.subscriptions.interfaces import (
    PlanRepository,
    SubscriptionRepository,
)


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

    async def list_services(self, telegram_id: int) -> list[Subscription]:
        return await self.repository.list_for_user(
            telegram_id,
            statuses=frozenset(
                {
                    SubscriptionStatus.ACTIVE,
                    SubscriptionStatus.EXPIRED,
                    SubscriptionStatus.SUSPENDED,
                }
            ),
        )

    async def list_orders(self, telegram_id: int) -> list[Subscription]:
        return await self.repository.list_for_user(
            telegram_id,
            statuses=frozenset(
                {
                    SubscriptionStatus.PENDING_PAYMENT,
                    SubscriptionStatus.PAID_AWAITING_PROVISIONING,
                    SubscriptionStatus.TEST_AWAITING_PROVISIONING,
                }
            ),
        )

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
            duration_days=plan.duration_days,
        )
        await self.repository.create(record)
        return record
