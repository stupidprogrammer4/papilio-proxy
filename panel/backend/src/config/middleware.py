from fastapi import Request
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


class RequestBodyLimitMiddleware:
    def __init__(
        self, app: ASGIApp, max_bytes: int, receipt_bytes: int | None = None
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.receipt_bytes = receipt_bytes

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        budget = self.max_bytes
        if self.receipt_bytes is not None:
            routes = getattr(scope.get("app"), "routes", ())
            matched = next(
                (
                    route
                    for route in routes
                    if isinstance(route, APIRoute)
                    and scope["method"] in route.methods
                    and route.path_regex.fullmatch(scope["path"])
                    and (route.openapi_extra or {}).get("body_budget")
                    == "receipt"
                ),
                None,
            )
            if matched is not None:
                budget = self.receipt_bytes
        raw_length = dict(scope["headers"]).get(b"content-length")
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                response = Response(status_code=400)
                await response(scope, receive, send)
                return
            if length > budget:
                response = Response(status_code=413)
                await response(scope, receive, send)
                return
        total = 0

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > budget:
                    raise HTTPException(status_code=413)
            return message

        await self.app(scope, limited_receive, send)
