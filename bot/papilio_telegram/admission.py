import asyncio
import math
from collections.abc import Awaitable, Callable

from aiohttp import web


class WebhookAdmission:
    def __init__(
        self,
        capacity: int,
        max_request_bytes: int,
        processing_timeout_seconds: float,
    ) -> None:
        if (
            not math.isfinite(processing_timeout_seconds)
            or min(capacity, max_request_bytes, processing_timeout_seconds)
            <= 0
        ):
            raise ValueError("Webhook capacities must be positive")
        self.capacity, self.max_request_bytes = capacity, max_request_bytes
        self.active = 0
        self.processing_timeout_seconds = processing_timeout_seconds
        self.middleware = self.handle

    @web.middleware
    async def handle(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if request.path != "/telegram/webhook":
            result = await handler(request)
            return result
        if self.active >= self.capacity:
            raise web.HTTPServiceUnavailable()
        if (
            request.content_length is not None
            and request.content_length > self.max_request_bytes
        ):
            raise web.HTTPRequestEntityTooLarge(
                max_size=self.max_request_bytes,
                actual_size=request.content_length,
            )
        self.active += 1
        try:
            async with asyncio.timeout(self.processing_timeout_seconds):
                bounded = request.clone(client_max_size=self.max_request_bytes)
                await bounded.read()
                result = await handler(bounded)
                return result
        except TimeoutError:
            raise web.HTTPServiceUnavailable() from None
        finally:
            self.active -= 1
