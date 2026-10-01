from __future__ import annotations

from html import escape
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from bot.models.access import SubscriptionAccess
from bot.services.access import AccessInactive, AccessService, AccessUnavailable


def _private_headers(access: SubscriptionAccess) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "subscription-userinfo": (
            f"upload={access.uplink_bytes}; download={access.downlink_bytes}; "
            f"total={access.traffic_limit_bytes}; expire={int(access.expires_at.timestamp())}"
        ),
    }


def build_subscription_router() -> APIRouter:
    router = APIRouter()

    async def resolve(request: Request, token: str) -> SubscriptionAccess | Response:
        service = cast("AccessService | None", request.app.state.access_service)
        if service is None:
            return PlainTextResponse("سرویس اشتراک فعلاً در دسترس نیست.", status_code=503)
        try:
            access = await service.get_by_token(token)
        except AccessInactive:
            return PlainTextResponse("اعتبار سرویس یا حجم آن تمام شده است.", status_code=410)
        except AccessUnavailable:
            return PlainTextResponse("اطلاعات مصرف تازه نیست؛ کمی بعد دوباره امتحان کنید.", status_code=503)
        if access is None:
            return PlainTextResponse("لینک اشتراک پیدا نشد.", status_code=404)
        return access

    @router.get("/s/{token}", response_class=PlainTextResponse)
    async def subscription(request: Request, token: str) -> Response:
        access = await resolve(request, token)
        if isinstance(access, Response):
            return access
        headers = _private_headers(access)
        public_base = cast("str | None", request.app.state.subscription_public_base_url)
        if public_base:
            headers["profile-web-page-url"] = f"{public_base}/usage/{token}"
        return PlainTextResponse(
            f"{access.vless_link}\n{access.vmess_link}\n",
            headers=headers,
            media_type="text/plain; charset=utf-8",
        )

    @router.get("/usage/{token}", response_class=HTMLResponse, name="subscription_usage")
    async def subscription_usage(request: Request, token: str) -> Response:
        access = await resolve(request, token)
        if isinstance(access, Response):
            return access
        used = access.traffic_used_bytes
        remaining = access.traffic_remaining_bytes
        total = access.traffic_limit_bytes
        percent = min(100, used * 100 // total)
        measured = access.last_measured_at
        measured_text = measured.strftime("%Y-%m-%d %H:%M UTC") if measured else "—"
        body = (
            "<!doctype html><html lang='fa' dir='rtl'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>مصرف اشتراک پاپیلیو</title>"
            "<style>body{font-family:system-ui,sans-serif;background:#0b1020;color:#f6f7ff;"
            "margin:0;display:grid;place-items:center;min-height:100vh;padding:1rem}"
            "main{width:min(100%,420px);background:#171f34;border:1px solid #33405d;"
            "border-radius:24px;padding:1.5rem;box-shadow:0 20px 60px #05091488}"
            "h1{font-size:1.35rem}p{color:#b9c5dc}strong{color:#fff}"
            "meter{width:100%;height:1.4rem;accent-color:#8d7bff}"
            "small{color:#9ba9c2}</style></head><body><main>"
            "<h1>🦋 وضعیت اشتراک تو</h1>"
            f"<p>📊 مصرف‌شده: <strong>{used / 1024**3:.2f} گیگابایت</strong></p>"
            f"<p>✨ باقیمانده: <strong>{remaining / 1024**3:.2f} گیگابایت</strong></p>"
            f"<p>📦 حجم کل: <strong>{total / 1024**3:.2f} گیگابایت</strong></p>"
            f"<meter min='0' max='100' value='{percent}'>{percent}%</meter>"
            f"<p>🗓 پایان: <strong>{escape(access.expires_at.strftime('%Y-%m-%d %H:%M UTC'))}</strong></p>"
            f"<small>آخرین اندازه‌گیری: {escape(measured_text)} · مجموع آپلود و دانلود</small>"
            "</main></body></html>"
        )
        return HTMLResponse(body, headers=_private_headers(access))

    return router
