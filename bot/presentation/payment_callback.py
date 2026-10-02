from __future__ import annotations

from html import escape
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from bot.models.payments import PaymentProviderUnavailable
from bot.services.payments import (
    CallbackOutcome,
    PaymentSettlementError,
    PaymentVerificationService,
)


def build_payment_router() -> APIRouter:
    router = APIRouter()

    @router.get("/payments/kpay/callback", response_class=PlainTextResponse)
    async def callback(request: Request) -> Response:
        authorities = request.query_params.getlist("authority")
        if len(authorities) != 1 or not 1 <= len(authorities[0]) <= 256:
            return PlainTextResponse("درخواست پرداخت معتبر نیست.", status_code=400)
        service = cast("PaymentVerificationService | None", request.app.state.payment_service)
        if service is None:
            return PlainTextResponse("بررسی پرداخت فعلاً در دسترس نیست.", status_code=503)
        try:
            result = await service.verify_callback(authorities[0])
        except PaymentProviderUnavailable:
            return PlainTextResponse("بررسی پرداخت فعلاً در دسترس نیست.", status_code=503)
        except PaymentSettlementError:
            return PlainTextResponse("پرداخت به سفارش معتبری متصل نشد؛ با پشتیبانی تماس بگیرید.", status_code=409)
        paid = result == CallbackOutcome.PAID
        title = "✅ پرداخت تأیید شد" if paid else "⏳ پرداخت هنوز تأیید نشده است"
        detail = "سفارش وارد صف فعال‌سازی شد. وضعیت تحویل سرویس را در بات بررسی کنید." if paid else "پس از انتقال وجه، در بات «بررسی پرداخت» را بزن. رسید به‌تنهایی تأیید نیست."
        destination = cast("str | None", getattr(request.app.state, "bot_return_url", None))
        order_id = await service.return_order_id(authorities[0])
        if destination and order_id:
            destination += "?start=paid_" + order_id
        action = f'<div class="actions"><a href="{escape(destination, quote=True)}">🦋 بازگشت به بات</a></div>' if destination else ""
        redirect = (
            f'<p>در حال بازگشت به چت… اگر باز نشد، دکمهٔ بالا را بزن.</p>'
            f'<div id="payment-return" data-url="{escape(destination, quote=True)}"></div>'
            '<script src="/subscription-assets/payment-return.js" defer></script>'
        ) if paid and destination else ""
        return HTMLResponse(
            '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>پرداخت پاپیلیو</title>'
            '<link rel="stylesheet" href="/subscription-assets/subscription.css"></head><body><main>'
            f'<section class="dashboard"><h1>{title}</h1><p>{detail}</p>{action}{redirect}</section>'
            '</main></body></html>', headers={
                "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            },
        )

    @router.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return router
