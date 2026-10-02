import asyncio
import base64
import hashlib
from typing import Protocol

from bot.models.payments import PaymentProviderUnavailable, ProviderVerification
from bot.models.receipts import ReceiptOrder, ReceiptPaymentPage, ReceiptUnavailable
from bot.services.payments import PaymentRepository, PaymentSettlementError


class ReceiptRepository(Protocol):
    async def enabled(self) -> bool: ...
    async def set_enabled(self, enabled: bool) -> None: ...
    async def bound_order(self, authority: str) -> ReceiptOrder | None: ...
    async def reserve(self, order_id: str, digest: str) -> bool: ...
    async def mark_uploaded(self, order_id: str) -> None: ...
    async def pending_uploads(self, limit: int = 5) -> list[str]: ...


class ReceiptProvider(Protocol):
    async def verify(self, authority: str) -> ProviderVerification: ...
    async def payment_page(self, authority: str) -> ReceiptPaymentPage: ...
    async def upload_receipt(self, authority: str, image: str) -> None: ...


class ReceiptService:
    """Submit receipts to KPay and observe its own decision; never approve on its behalf."""

    def __init__(self, repository: ReceiptRepository, provider: ReceiptProvider,
                 payments: PaymentRepository) -> None:
        self.repository = repository
        self._provider = provider
        self._payments = payments
        self._locks = [asyncio.Lock() for _ in range(64)]

    def _lock(self, authority: str) -> asyncio.Lock:
        return self._locks[hashlib.sha256(authority.encode()).digest()[0] % len(self._locks)]

    async def page(self, authority: str) -> ReceiptPaymentPage:
        if not await self.repository.enabled():
            raise ReceiptUnavailable("تأیید خودکار رسید خاموش است.")
        order = await self.repository.bound_order(authority)
        if order is None:
            raise ReceiptUnavailable("سفارش پرداخت‌نشده پیدا نشد؛ دوباره پرداخت نکن.")
        page = await self._provider.payment_page(authority)
        if page.amount_rial != order.amount_rial:
            raise ReceiptUnavailable("مبلغ درگاه با سفارش مطابقت ندارد.")
        if page.status != "pending" or page.remaining_seconds <= 0:
            raise ReceiptUnavailable("مهلت این پرداخت تمام شده یا قبلاً تأیید شده؛ دوباره پرداخت نکن.")
        return page

    @staticmethod
    def _matches(order: ReceiptOrder, result: ProviderVerification) -> None:
        if (result.authority != order.authority or result.transaction_id != order.transaction_id
                or result.amount_rial != order.amount_rial):
            raise PaymentSettlementError("Provider receipt does not match the stored order")

    async def _finish(self, authority: str) -> bool:
        if not await self.repository.enabled():
            return False
        order = await self.repository.bound_order(authority)
        if order is None:
            return False
        result = await self._provider.verify(authority)
        self._matches(order, result)
        if not result.verified:
            if result.status != "pending":
                raise ReceiptUnavailable("وضعیت رسید قابل تأیید نیست.")
            return False
        if result.verified:
            if not await self._payments.settle_verified(result):
                raise PaymentSettlementError("Receipt order settlement failed")
            return True
        return False

    async def submit(self, authority: str, image: str) -> bool:
        prefix, separator, encoded = image.partition(",")
        if not separator or prefix not in {"data:image/png;base64", "data:image/jpeg;base64"}:
            raise ReceiptUnavailable("رسید باید تصویر PNG یا JPEG باشد.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ReceiptUnavailable("تصویر رسید معتبر نیست.") from exc
        if not 1 <= len(content) <= 2_000_000 or not (
            content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
        ):
            raise ReceiptUnavailable("تصویر رسید معتبر نیست یا بزرگ‌تر از ۲ مگابایت است.")
        async with self._lock(authority):
            await self.page(authority)
            order = await self.repository.bound_order(authority)
            if order is None:
                raise ReceiptUnavailable("سفارش در دسترس نیست.")
            uploaded = await self.repository.reserve(order.order_id, hashlib.sha256(content).hexdigest())
            if not uploaded:
                await self._provider.upload_receipt(authority, image)
                await self.repository.mark_uploaded(order.order_id)
            return await self._finish(authority)

    async def recheck_uploaded(self) -> int:
        if not await self.repository.enabled():
            return 0
        paid = 0
        for authority in await self.repository.pending_uploads():
            try:
                async with self._lock(authority):
                    paid += await self._finish(authority)
            except (PaymentProviderUnavailable, PaymentSettlementError, ReceiptUnavailable):
                continue
        return paid
