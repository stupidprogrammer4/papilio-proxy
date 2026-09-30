from __future__ import annotations

from dataclasses import replace
from unittest import IsolatedAsyncioTestCase

from bot.services.subscriptions import (
    Plan,
    PlanRepository,
    Protocol,
    Subscription,
    SubscriptionRepository,
    SubscriptionService,
    TelegramUser,
)


class MemorySubscriptionRepository(SubscriptionRepository, PlanRepository):
    def __init__(self) -> None:
        self.users: dict[int, TelegramUser] = {}
        self.records: list[Subscription] = []
        self.plans: dict[str, Plan] = {}

    async def upsert_user(self, user: TelegramUser) -> None:
        self.users[user.telegram_id] = user

    async def list_for_user(self, telegram_id: int) -> list[Subscription]:
        return [record for record in self.records if record.telegram_id == telegram_id]

    async def create(self, subscription: Subscription) -> None:
        self.records.append(subscription)

    async def list(self, *, active_only: bool = True) -> list[Plan]:
        plans = self.plans.values()
        if active_only:
            plans = (plan for plan in plans if plan.is_active)
        return sorted(plans, key=lambda plan: (plan.sort_order, plan.code))

    async def get(self, code: str) -> Plan | None:
        return self.plans.get(code)

    async def save(self, plan: Plan) -> None:
        self.plans[plan.code] = plan

    async def set_active(self, code: str, is_active: bool) -> None:
        self.plans[code] = replace(self.plans[code], is_active=is_active)

    async def delete(self, code: str) -> None:
        del self.plans[code]


class SubscriptionServiceTests(IsolatedAsyncioTestCase):
    async def test_order_persists_traffic_and_protocol(self) -> None:
        repository = MemorySubscriptionRepository()
        service = SubscriptionService(repository, repository)
        await service.register_user(TelegramUser(77, "کاربر آزمایشی", "sample"))
        await repository.save(Plan("m60", "همراه", 60, 30, 990_000))

        order = await service.create_order(77, "m60", Protocol.VLESS)
        subscriptions = await service.list_subscriptions(77)

        self.assertEqual(len(subscriptions), 1)
        self.assertEqual(subscriptions[0].id, order.id)
        self.assertEqual(subscriptions[0].protocol, Protocol.VLESS)
        self.assertEqual(subscriptions[0].traffic_limit_bytes, 60 * 1024**3)
        self.assertEqual(subscriptions[0].price_rial, 990_000)
