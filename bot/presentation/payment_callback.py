from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from bot.models.payments import PaymentProviderUnavailable
from bot.services.payments import PaymentVerificationService


def build_payment_router() -> APIRouter:
    router = APIRouter()

    @router.get("/payments/kpay/callback", response_class=PlainTextResponse)
    async def callback(request: Request) -> PlainTextResponse:
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
        if result.verified:
            return PlainTextResponse(
                "پرداخت در KPay تأیید شده است؛ وضعیت سفارش و فعال‌سازی سرویس هنوز بررسی نشده‌اند."
            )
        return PlainTextResponse("پرداخت در KPay هنوز تأیید نشده است.")

    @router.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return router
