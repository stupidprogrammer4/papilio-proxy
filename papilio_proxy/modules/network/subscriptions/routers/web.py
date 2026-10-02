from __future__ import annotations

import base64
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from papilio_proxy.modules.network.subscriptions.app.services import (
    AccessInactive,
    AccessService,
    AccessUnavailable,
)
from papilio_proxy.modules.network.subscriptions.domain.entities import SubscriptionAccess
from papilio_proxy.modules.network.subscriptions.routers.views import (
    connection_links,
    subscription_page,
)


def _private_headers(access: SubscriptionAccess) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "profile-title": "base64:" + base64.b64encode(access.profile_name.encode()).decode(),
        "profile-update-interval": "6",
        "Content-Security-Policy": "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
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
            return PlainTextResponse(
                "اطلاعات مصرف تازه نیست؛ کمی بعد دوباره امتحان کنید.", status_code=503
            )
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
        if "text/html" in request.headers.get("accept", ""):
            return HTMLResponse(subscription_page(access, public_base), headers=headers)
        return PlainTextResponse(
            "\n".join(connection_links(access)) + "\n",
            headers=headers,
            media_type="text/plain; charset=utf-8",
        )

    @router.get("/usage/{token}", response_class=HTMLResponse, name="subscription_usage")
    async def subscription_usage(request: Request, token: str) -> Response:
        access = await resolve(request, token)
        if isinstance(access, Response):
            return access
        public_base = cast("str | None", request.app.state.subscription_public_base_url)
        return HTMLResponse(
            subscription_page(access, public_base), headers=_private_headers(access)
        )

    return router


router = build_subscription_router()
