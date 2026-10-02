from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from papilio_proxy.modules.network.subscriptions.app.trials import TestAccessService


class FakePilotRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    async def grant(self, telegram_id: int, quota_bytes: int, duration_days: int) -> str:
        self.calls.append((telegram_id, quota_bytes, duration_days))
        return "pilot-order-id"


class TestAccessServiceTests(IsolatedAsyncioTestCase):
    async def test_only_admin_receives_bounded_entitlement(self) -> None:
        repository = FakePilotRepository()
        service = TestAccessService(repository, frozenset({42}))
        with self.assertRaises(PermissionError):
            await service.grant(41, 512, 1)
        with self.assertRaises(ValueError):
            await service.grant(42, 0, 1)
        with self.assertRaises(ValueError):
            await service.grant(42, 512, 8)
        self.assertEqual(await service.grant(42, 512, 1), "pilot-order-id")
        self.assertEqual(repository.calls, [(42, 512 * 1024**2, 1)])
