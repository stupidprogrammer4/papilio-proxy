import re
from html import escape
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from bot.models.payments import PaymentProviderUnavailable
from bot.models.receipts import ReceiptUnavailable
from bot.services.payments import PaymentSettlementError
from bot.services.receipts import ReceiptService


class ReceiptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str = Field(min_length=30, max_length=2_700_000)


def _service(request: Request) -> ReceiptService:
    service = cast("ReceiptService | None", request.app.state.receipt_service)
    if service is None:
        raise HTTPException(503, "تأیید خودکار رسید در دسترس نیست.")
    return service


def build_receipt_router() -> APIRouter:
    router = APIRouter()

    @router.get("/payments/kpay/checkout/{authority}", response_class=HTMLResponse)
    async def checkout(authority: str, request: Request) -> HTMLResponse:
        if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", authority) is None:
            raise HTTPException(404)
        try:
            page = await _service(request).page(authority)
        except ReceiptUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except PaymentProviderUnavailable as exc:
            raise HTTPException(503, "اطلاعات پرداخت در دسترس نیست؛ فعلاً واریز نکن.") from exc
        card = " ".join(page.card_number[i:i+4] for i in range(0, 16, 4))
        amount = f"{page.final_amount_rial / 10:,.1f}".removesuffix(".0")
        return HTMLResponse(
            '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>🦋 پرداخت پاپیلیو</title><link rel="stylesheet" href="/subscription-assets/subscription.css">'
            '<script src="/subscription-assets/receipt-checkout.js" defer></script></head><body><main>'
            '<section class="dashboard"><span class="eyebrow">PAPILIO · KPAY</span>'
            '<h1>💳 پرداخت و دریافت خودکار سرویس</h1>'
            '<p>۱️⃣ مبلغ دقیق را به کارت زیر منتقل کن.<br>۲️⃣ تصویر رسید را همین‌جا ارسال کن.'
            '<br>۳️⃣ نتیجهٔ KPay خودکار پیگیری می‌شود؛ پس از تأیید، لینک‌ها و QR در بات ارسال می‌شوند.</p>'
            f'<h2>💰 {amount} تومان</h2><p>مبلغ نهایی درگاه؛ کارمزد بانک ممکن است جدا باشد.</p>'
            f'<h2 dir="ltr">{card}</h2><p>👤 {escape(page.owner_name)}</p>'
            '<div class="actions"><button id="copy-card" type="button" '
            f'data-card="{page.card_number}">📋 کپی شماره کارت</button></div>'
            '<form id="receipt-form"><p><label for="receipt">🧾 تصویر رسید (PNG یا JPEG، تا ۲ مگابایت)</label></p>'
            '<input id="receipt" type="file" accept="image/png,image/jpeg" required>'
            '<div class="actions"><button type="submit">✅ ارسال رسید و تأیید خودکار</button></div></form>'
            '<p id="receipt-status" role="status" aria-live="polite"></p>'
            '<p>🔒 لینک این صفحه خصوصی است. اگر وجه را واریز کرده‌ای، دوباره پرداخت نکن.</p>'
            '</section></main></body></html>',
        )

    @router.post("/payments/kpay/checkout/{authority}/receipt")
    async def submit(authority: str, request: Request) -> dict[str, object]:
        origin = request.headers.get("origin", "")
        expected = cast("str | None", request.app.state.admin_public_origin)
        if not expected or origin != expected:
            raise HTTPException(403, "مبدأ درخواست معتبر نیست.")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", authority) is None:
            raise HTTPException(404)
        # Bound memory even for chunked input before JSON/base64 parsing.
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 2_701_000:
                raise HTTPException(413, "تصویر رسید بزرگ‌تر از حد مجاز است.")
        try:
            body = ReceiptBody.model_validate_json(content)
        except ValueError as exc:
            raise HTTPException(422, "تصویر رسید معتبر نیست.") from exc
        try:
            paid = await _service(request).submit(authority, body.image)
        except ReceiptUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except (PaymentProviderUnavailable, PaymentSettlementError) as exc:
            raise HTTPException(503, "پاسخ قطعی درگاه نرسید؛ دوباره پرداخت نکن. بررسی خودکار ادامه دارد.") from exc
        return {"paid": paid, "callback": f"/payments/kpay/callback?authority={authority}"}

    return router
