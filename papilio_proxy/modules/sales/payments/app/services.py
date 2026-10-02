from dataclasses import dataclass
from uuid import UUID, uuid4

from papilio_proxy.modules.sales.payments.domain.entities import (
    PaymentError,
    PaymentInstructions,
    PaymentKind,
    PaymentMethod,
    PaymentReceipt,
    ReceiptStatus,
)

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


from papilio_proxy.modules.sales.payments.interfaces import PaymentRepository


@dataclass(slots=True)
class PaymentService:
    repository: PaymentRepository

    async def enabled(self, telegram_id: int | None = None) -> bool:
        return bool(await self.repository.methods(enabled_only=True))

    async def methods(self, *, enabled_only: bool = False) -> list[PaymentMethod]:
        return await self.repository.methods(enabled_only=enabled_only)

    async def save_method(
        self,
        *,
        method_id: str | None,
        title: str,
        card_number: str,
        bank_name: str,
        account_holder: str,
        enabled: bool,
    ) -> PaymentMethod:
        card = card_number.translate(DIGITS).replace(" ", "").replace("-", "")
        if not card.isascii() or not card.isdecimal() or len(card) != 16:
            raise PaymentError("شماره کارت باید ۱۶ رقم باشد.")
        fields = (title.strip(), bank_name.strip(), account_holder.strip())
        if any(not value or len(value) > 100 or "\x00" in value for value in fields):
            raise PaymentError("عنوان، بانک و نام صاحب حساب را کامل وارد کنید.")
        if method_id:
            try:
                method_id = str(UUID(method_id))
            except ValueError as exc:
                raise PaymentError("روش پرداخت معتبر نیست.") from exc
        method = PaymentMethod(
            method_id or str(uuid4()),
            PaymentKind.CARD_TO_CARD,
            fields[0],
            card,
            fields[1],
            fields[2],
            enabled,
        )
        await self.repository.save_method(method)
        return method

    async def begin(self, telegram_id: int, plan_code: str, method_id: str) -> PaymentInstructions:
        return await self.repository.begin(telegram_id, plan_code, method_id)

    async def instructions(self, telegram_id: int, order_id: str) -> PaymentInstructions:
        return await self.repository.instructions(telegram_id, order_id)

    async def submit_receipt(self, telegram_id: int, order_id: str, image: bytes) -> str:
        return await self.repository.submit_receipt(telegram_id, order_id, image)

    async def status(self, telegram_id: int, order_id: str) -> ReceiptStatus | None:
        return await self.repository.receipt_status(telegram_id, order_id)

    async def receipts(self, offset: int = 0) -> list[PaymentReceipt]:
        return await self.repository.receipts(offset=offset)

    async def receipt_image(self, receipt_id: str) -> bytes:
        return await self.repository.receipt_image(receipt_id)

    async def review(
        self,
        receipt_id: str,
        *,
        approved: bool,
        actor: str,
        bank_reference: str = "",
        reason: str = "",
    ) -> None:
        reference = "".join(bank_reference.translate(DIGITS).split()).replace("-", "").upper()
        if approved and (
            not reference
            or len(reference) > 128
            or not reference.isascii()
            or not reference.isalnum()
        ):
            raise PaymentError("شناسهٔ تراکنش بانکی را برای تأیید وارد کنید.")
        if not approved and not reason.strip():
            raise PaymentError("دلیل رد رسید را وارد کنید.")
        if len(reason.strip()) > 300:
            raise PaymentError("دلیل رد رسید بیش از حد طولانی است.")
        await self.repository.review(receipt_id, approved, actor, reference, reason.strip())
