from dataclasses import replace
from unittest import IsolatedAsyncioTestCase

from bot.services.admin_plans import AdminAccessError, AdminPlanService, PlanValidationError
from bot.services.subscriptions import Protocol, SubscriptionService, UnknownPlanError
from tests.unit.test_subscriptions import MemorySubscriptionRepository


class AdminPlanTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = MemorySubscriptionRepository()
        self.admin = AdminPlanService(self.repository, frozenset({77}))
        self.customer = SubscriptionService(self.repository, self.repository)

    async def create_plan(self) -> None:
        await self.admin.save_plan(
            77,
            code="test",
            title="تست",
            traffic_gb=17,
            duration_days=21,
            price_rial=123_450,
            sort_order=10,
            emoji="⚡",
        )

    async def test_new_plan_is_hidden_until_activated_and_never_seeds_defaults(self) -> None:
        self.assertEqual(await self.customer.list_plans(), [])
        await self.create_plan()
        self.assertEqual(await self.customer.list_plans(), [])
        await self.admin.set_active(77, "test", True)
        plans = await self.customer.list_plans()
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].price_rial, 123_450)
        self.assertEqual(plans[0].price_toman, 12_345)
        self.assertEqual(plans[0].emoji, "⚡")

    async def test_emoji_is_editable_and_plain_text_is_rejected(self) -> None:
        await self.create_plan()
        changed = await self.admin.save_plan(
            77,
            code="test",
            title="تست",
            traffic_gb=17,
            duration_days=21,
            price_rial=123_450,
            sort_order=10,
            emoji="🚀",
            editing=True,
        )
        self.assertEqual(changed.emoji, "🚀")
        self.assertEqual((await self.customer.get_plan("test")).emoji, "🚀")
        with self.assertRaises(PlanValidationError):
            await self.admin.save_plan(
                77,
                code="test",
                title="تست",
                traffic_gb=17,
                duration_days=21,
                price_rial=123_450,
                sort_order=10,
                emoji="abc",
                editing=True,
            )

    async def test_unknown_and_inactive_plans_cannot_create_orders(self) -> None:
        with self.assertRaises(UnknownPlanError):
            await self.customer.create_order(77, "unknown", Protocol.VMESS)
        await self.create_plan()
        with self.assertRaises(UnknownPlanError):
            await self.customer.create_order(77, "test", Protocol.VMESS)
        self.assertEqual(self.repository.records, [])

    async def test_unauthorized_mutation_leaves_plan_unchanged(self) -> None:
        await self.create_plan()
        with self.assertRaises(AdminAccessError):
            await self.admin.set_active(88, "test", True)
        self.assertFalse(self.repository.plans["test"].is_active)

    async def test_duplicate_plan_does_not_overwrite(self) -> None:
        await self.create_plan()
        with self.assertRaises(PlanValidationError):
            await self.create_plan()
        self.assertEqual(len(self.repository.plans), 1)

    async def test_order_snapshot_does_not_change_with_plan_edit(self) -> None:
        await self.create_plan()
        await self.admin.set_active(77, "test", True)
        order = await self.customer.create_order(77, "test", Protocol.VMESS)
        await self.repository.save(replace(self.repository.plans["test"], traffic_gb=99))
        self.assertEqual(order.traffic_limit_bytes, 17 * 1024**3)
        self.assertEqual(order.price_rial, 123_450)
        self.assertEqual(await self.customer.list_subscriptions(88), [])
