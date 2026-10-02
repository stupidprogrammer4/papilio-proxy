from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from bot.models.payments import ProviderVerification
from bot.services.payments import (
    CallbackOutcome,
    PaymentSettlementError,
    PaymentVerificationService,
)


class PaymentServiceTests(IsolatedAsyncioTestCase):
    async def test_return_link_contains_order_id_not_authority(self) -> None:
        repository = AsyncMock()
        identifier = "123e4567-e89b-42d3-a456-426614174000"
        repository.order_id_for_authority.return_value = identifier
        service = PaymentVerificationService(AsyncMock(), repository)
        self.assertEqual(await service.return_order_id("private-authority"), identifier)
        repository.order_id_for_authority.return_value = "not-a-uuid"
        self.assertIsNone(await service.return_order_id("private-authority"))

    async def test_background_check_wraps_cursor_and_settles_without_callback(self) -> None:
        repository = AsyncMock()
        provider = AsyncMock()
        repository.pending_authorities.side_effect = [["a"], [], ["a"]]
        repository.has_authority.return_value = True
        repository.settle_verified.return_value = True
        provider.verify.return_value = ProviderVerification(
            "a", "paid", "tx", 590_000, "2026-10-01T00:00:00Z"
        )
        service = PaymentVerificationService(provider, repository)
        self.assertEqual(await service.recheck_pending(), 1)
        self.assertEqual(await service.recheck_pending(), 1)
        self.assertEqual(repository.pending_authorities.await_args_list[1].args, ("a", 5))
        self.assertEqual(repository.pending_authorities.await_args_list[2].args, (None, 5))

    async def test_unknown_authority_never_calls_kpay(self) -> None:
        provider = AsyncMock()
        repository = AsyncMock()
        repository.has_authority.return_value = False
        service = PaymentVerificationService(provider, repository)

        with self.assertRaises(PaymentSettlementError):
            await service.verify_callback("unknown")
        provider.verify.assert_not_awaited()

    async def test_unpaid_provider_result_does_not_touch_order(self) -> None:
        provider = AsyncMock()
        repository = AsyncMock()
        provider.verify.return_value = ProviderVerification("a", "pending", "tx", 590_000, None)
        repository.has_authority.return_value = True
        service = PaymentVerificationService(provider, repository)

        result = await service.verify_callback("a")

        self.assertEqual(result, CallbackOutcome.NOT_PAID)
        repository.settle_verified.assert_not_awaited()

    async def test_paid_provider_result_requires_bound_order(self) -> None:
        provider = AsyncMock()
        repository = AsyncMock()
        provider.verify.return_value = ProviderVerification(
            "a", "paid", "tx", 590_000, "2026-10-01T00:00:00Z"
        )
        repository.has_authority.return_value = True
        repository.settle_verified.return_value = False
        service = PaymentVerificationService(provider, repository)

        with self.assertRaises(PaymentSettlementError):
            await service.verify_callback("a")
        repository.settle_verified.assert_awaited_once()

    async def test_paid_bound_order_is_only_awaiting_provisioning(self) -> None:
        provider = AsyncMock()
        repository = AsyncMock()
        provider.verify.return_value = ProviderVerification(
            "a", "paid", "tx", 590_000, "2026-10-01T00:00:00Z"
        )
        repository.has_authority.return_value = True
        repository.settle_verified.return_value = True
        service = PaymentVerificationService(provider, repository)

        result = await service.verify_callback("a")

        self.assertEqual(result, CallbackOutcome.PAID)
