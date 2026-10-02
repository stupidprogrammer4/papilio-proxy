import asyncio
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from bot.models.checkout import CheckoutConfig, CheckoutOrder, CheckoutUnavailable
from bot.models.payments import PaymentInitiation, PaymentProviderUnavailable
from bot.models.subscriptions import SubscriptionStatus
from bot.services.payments import CallbackOutcome, PaymentRepository, PaymentVerificationService


class CheckoutRepository(Protocol):
    async def get_config(self) -> CheckoutConfig: ...
    async def save_config(self, value: CheckoutConfig) -> None: ...
    async def get_order(self, telegram_id: int, order_id: str) -> CheckoutOrder | None: ...
    async def claim(self, order_id: str) -> None: ...


class CheckoutProvider(Protocol):
    async def create_transaction(
        self, *, shop_id: str, card_id: str, amount_rial: int, callback_url: str,
        order_id: str, description: str,
    ) -> PaymentInitiation: ...


@dataclass(slots=True)
class CheckoutService:
    repository: CheckoutRepository
    provider: CheckoutProvider
    payments: PaymentRepository
    verification: PaymentVerificationService
    admin_ids: frozenset[int] = frozenset()
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def enabled(self, telegram_id: int | None = None) -> bool:
        config = await self.repository.get_config()
        return bool(config.shop_id and config.card_id and config.callback_url) and (
            config.enabled or telegram_id in self.admin_ids
        )

    async def save_config(self, config: CheckoutConfig) -> None:
        parsed = urlsplit(config.callback_url)
        try:
            UUID(config.shop_id)
            UUID(config.card_id)
        except ValueError as exc:
            raise ValueError("شناسهٔ فروشگاه و کارت باید UUID معتبر باشند.") from exc
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path != "/payments/kpay/callback" or parsed.query or parsed.fragment
        ):
            raise ValueError("کالبک باید آدرس HTTPS معتبر همین سرویس باشد.")
        await self.repository.save_config(config)

    async def begin(self, telegram_id: int, order_id: str) -> PaymentInitiation:
        async with self._lock:
            if not await self.enabled(telegram_id):
                raise CheckoutUnavailable("خرید عمومی هنوز باز نشده است؛ فعلاً مبلغی واریز نکن.")
            order = await self.repository.get_order(telegram_id, order_id)
            if order is None or order.status != SubscriptionStatus.PENDING_PAYMENT.value:
                raise CheckoutUnavailable("سفارش پرداخت‌نشده پیدا نشد.")
            if order.checkout:
                return order.checkout
            await self.repository.claim(order_id)
            config = await self.repository.get_config()
            try:
                checkout = await self.provider.create_transaction(
                    shop_id=config.shop_id, card_id=config.card_id,
                    amount_rial=order.amount_rial, callback_url=config.callback_url,
                    order_id=order.id, description="Papilio · " + order.id[:8],
                )
                await self.payments.attach_checkout(order.id, checkout)
            except (PaymentProviderUnavailable, RuntimeError) as exc:
                raise CheckoutUnavailable("درگاه پاسخ قطعی نداد؛ برای بررسی با پشتیبانی تماس بگیر.") from exc
            return checkout

    async def check(self, telegram_id: int, order_id: str) -> CallbackOutcome:
        order = await self.repository.get_order(telegram_id, order_id)
        if order is None or order.checkout is None:
            raise CheckoutUnavailable("پرداختی برای این سفارش پیدا نشد.")
        return await self.verification.verify_callback(order.checkout.authority)
