import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from papilio.api.application import create_app as create_papilio_app
from papilio.core.config import Settings as FrameworkSettings

from papilio_proxy.config.database import Base, DatabaseConnection
from papilio_proxy.config.providers import RuntimeProvider
from papilio_proxy.config.settings import ConfigurationError, Settings
from papilio_proxy.modules.accounts.admin.app.services import AdminWebService
from papilio_proxy.modules.accounts.admin.routers.web import ASSETS as ADMIN_ASSETS
from papilio_proxy.modules.accounts.users.app.services import UserAccessService
from papilio_proxy.modules.network.nodes.infra.client import XrayNodeClient
from papilio_proxy.modules.network.subscriptions.app.services import AccessService
from papilio_proxy.modules.network.subscriptions.routers.views import ASSETS as SUBSCRIPTION_ASSETS
from papilio_proxy.modules.sales.payments.app.services import PaymentService


def framework_settings() -> FrameworkSettings:
    return FrameworkSettings.model_validate(
        {
            "app": {"modules": ["papilio_proxy.modules"]},
            "fastapi": {
                "title": "Subscription API",
                "description": "Private owner console and customer subscriptions",
                "version": "0.1.0",
            },
            "storage": {
                "path": "/tmp/papilio/media",
                "temp_dir": "/tmp/papilio/tmp",
                "max_file_size": 5,
                "allowed_extensions": ["jpg", "png", "webp"],
            },
            "logging": {"level": "WARNING", "format": "console", "service": "subscriptions"},
        }
    )


def create_app(access_service: AccessService | None = None) -> FastAPI:
    try:
        settings = Settings.from_environment(require_token=False)
    except ConfigurationError:
        settings = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings is None:
            raise ConfigurationError("تنظیمات محیط API کامل نیست.")
        for name in ("uvicorn.access", "httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
        container = app.state.dishka_container
        database = await container.get(DatabaseConnection)
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        app.state.payment_service = await container.get(PaymentService)
        app.state.access_service = access_service or await container.get(AccessService)
        app.state.private_node = await container.get(XrayNodeClient | None)
        app.state.subscription_public_base_url = settings.subscription_public_base_url
        origin = os.getenv("ADMIN_PUBLIC_ORIGIN", "").strip().rstrip("/")
        parsed = urlsplit(origin)
        if (
            origin
            and parsed.scheme == "https"
            and parsed.hostname
            and not any(
                (parsed.path, parsed.query, parsed.fragment, parsed.username, parsed.password)
            )
        ):
            app.state.admin_public_origin = origin
            app.state.admin_web_service = await container.get(AdminWebService)
            app.state.admin_user_access_service = await container.get(UserAccessService)
        yield

    health = APIRouter()

    @health.get("/healthz")
    async def healthz() -> Response:
        return Response("ok", media_type="text/plain")

    app = create_papilio_app(
        framework_settings(),
        providers=[RuntimeProvider(settings)],
        routers=[health],
        middleware=(),
        docs_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.payment_service = None
    app.state.access_service = access_service
    app.state.private_node = None
    app.state.subscription_public_base_url = None
    app.state.admin_web_service = None
    app.state.admin_user_access_service = None
    app.state.admin_public_origin = None
    app.mount("/admin/assets", StaticFiles(directory=ADMIN_ASSETS), name="admin-assets")
    app.mount(
        "/subscription-assets",
        StaticFiles(directory=SUBSCRIPTION_ASSETS),
        name="subscription-assets",
    )

    @app.middleware("http")
    async def admin_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/admin"):
            response.headers.update(
                {
                    "Cache-Control": "private, no-store, max-age=0",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                    "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                }
            )
        return response

    return app


app = create_app()
