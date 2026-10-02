from typing import cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from bot.models.checkout import CheckoutConfig, CheckoutOrder, CheckoutUnavailable
from bot.models.payments import PaymentInitiation, PaymentProviderUnavailable
from bot.services.checkout import CheckoutService


class CheckoutTests(IsolatedAsyncioTestCase):
    async def test_customer_always_gets_provider_link_even_with_receipt_page_enabled(self) -> None:
        service = self.service()
        service.receipts = AsyncMock()
        checkout = PaymentInitiation("tx", "auth", 50_000, "https://kpay.website/pay/auth")
        self.assertEqual(await service.customer_payment_url(checkout), checkout.payment_url)
        cast(AsyncMock, service.receipts).repository.enabled.assert_not_awaited()

    def service(self, enabled: bool = True) -> CheckoutService:
        repo, provider, payments, verification = (AsyncMock() for _ in range(4))
        repo.get_config.return_value = CheckoutConfig(enabled, "shop", "card", "https://example.test/payments/kpay/callback")
        repo.get_order.return_value = CheckoutOrder("order", 123450, "pending_payment")
        provider.create_transaction.return_value = PaymentInitiation("transaction", "authority", 123450, "https://kpay.website/pay/authority")
        return CheckoutService(repo, provider, payments, verification, frozenset({77}))

    async def test_public_checkout_is_gated_but_admin_can_test(self) -> None:
        service = self.service(False)
        self.assertFalse(await service.enabled(88))
        self.assertTrue(await service.enabled(77))
        with self.assertRaises(CheckoutUnavailable):
            await service.begin(88, "order")

    async def test_price_from_order_and_claim_before_provider(self) -> None:
        service = self.service()
        result = await service.begin(77, "order")
        self.assertEqual(result.amount_rial, 123450)
        cast(AsyncMock, service.repository).claim.assert_awaited_once_with("order")
        self.assertEqual(cast(AsyncMock, service.provider).create_transaction.await_args.kwargs["amount_rial"], 123450)
        cast(AsyncMock, service.payments).attach_checkout.assert_awaited_once_with("order", result)

    async def test_existing_checkout_is_reused_and_other_users_cannot_check(self) -> None:
        service = self.service()
        cast(AsyncMock, service.repository).get_order.return_value = None
        with self.assertRaises(CheckoutUnavailable):
            await service.check(88, "order")
        cast(AsyncMock, service.verification).verify_callback.assert_not_awaited()

    async def test_unknown_provider_result_is_not_retried_or_attached(self) -> None:
        service = self.service()
        cast(AsyncMock, service.provider).create_transaction.side_effect = PaymentProviderUnavailable("unavailable")
        with self.assertRaises(CheckoutUnavailable):
            await service.begin(77, "order")
        cast(AsyncMock, service.repository).claim.assert_awaited_once()
        cast(AsyncMock, service.payments).attach_checkout.assert_not_awaited()
