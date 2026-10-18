import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from papilio.api.application import create_app
from papilio.api.middlewares.rate_limit import RateLimitMiddleware
from papilio.core.config import get_settings
from papilio_tasks.apps.lifecycle import Producers
from starlette.middleware import Middleware

from src.apps.events import app as events_application
from src.apps.scheduler import app as scheduler_application
from src.config.middleware import (
    RequestBodyLimitMiddleware,
    SecurityHeadersMiddleware,
)
from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings

settings = get_settings(PapilioSettings)
health = APIRouter()


@health.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@asynccontextmanager
async def private_access_logs(app: FastAPI) -> AsyncIterator[None]:
    # Subscription URLs carry credentials; do not emit request paths.
    access = logging.getLogger("uvicorn.access")
    previous = access.disabled
    access.disabled = True
    try:
        async with Producers(scheduler_application, events_application)(app):
            yield
    finally:
        access.disabled = previous


app = create_app(
    settings,
    providers=infrastructure_providers(settings),
    routers=[health],
    middleware=[
        Middleware(SecurityHeadersMiddleware),
        Middleware(
            RequestBodyLimitMiddleware,
            max_bytes=settings.operations.max_request_body_bytes,
            receipt_bytes=settings.receipts.max_request_bytes,
        ),
        Middleware(RateLimitMiddleware),
    ],
    lifespan=private_access_logs,
    docs_url=None,
    openapi_url=None,
)
