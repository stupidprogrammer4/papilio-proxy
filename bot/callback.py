from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from papilio.api.application import create_app as create_papilio_app
from papilio.core.config import Settings as FrameworkSettings

from bot.core.config import ConfigurationError, Settings
from bot.infra.db.access import MysqlAccessRepository
from bot.infra.db.admin_web import MysqlAdminWebRepository
from bot.infra.db.checkout import MysqlCheckoutRepository
from bot.infra.db.credentials import MysqlCredentialVault
from bot.infra.db.dashboard import MysqlDashboardRepository
from bot.infra.db.mysql import MysqlSubscriptionRepository
from bot.infra.db.payments import MysqlPaymentRepository
from bot.infra.db.pricing import MysqlPricingRepository
from bot.infra.kpay import KpayVerifier
from bot.infra.node import XrayNodeClient
from bot.presentation.admin_web.routes import ASSETS as ADMIN_ASSETS
from bot.presentation.admin_web.routes import build_admin_web_router
from bot.presentation.payment_callback import build_payment_router
from bot.presentation.subscription_api import build_subscription_router
from bot.presentation.subscription_view import ASSETS as SUBSCRIPTION_ASSETS
from bot.services.access import AccessService
from bot.services.admin_plans import AdminPlanService
from bot.services.admin_web import AdminWebService
from bot.services.branding import BrandingService
from bot.services.checkout import CheckoutService
from bot.services.dashboard import DashboardService
from bot.services.payments import PaymentVerificationService
from bot.services.pricing import PricingService


def create_app(
    service: PaymentVerificationService | None = None,
    access_service: AccessService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Authorities and subscription tokens can appear in URLs; never log them.
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        vault: MysqlCredentialVault | None = None
        node_client: XrayNodeClient | None = None
        client: httpx.AsyncClient | None = None
        repository: MysqlPaymentRepository | None = None
        checkout_repository: MysqlCheckoutRepository | None = None
        access_repository: MysqlAccessRepository | None = None
        admin_repository: MysqlAdminWebRepository | None = None
        pricing_repository: MysqlPricingRepository | None = None
        admin_dashboard_repository: MysqlDashboardRepository | None = None
        admin_subscription_repository: MysqlSubscriptionRepository | None = None
        if service is None:
            try:
                settings = Settings.from_environment(require_token=False)
                app.state.subscription_public_base_url = settings.subscription_public_base_url
                if settings.kpay_api_base_url and settings.credential_encryption_key:
                    vault = MysqlCredentialVault(
                        settings.database_url, settings.credential_encryption_key
                    )
                    client = httpx.AsyncClient(timeout=10.0, follow_redirects=False)
                    repository = MysqlPaymentRepository(settings.database_url)
                    await repository.initialize()
                    app.state.payment_service = PaymentVerificationService(
                        KpayVerifier(settings.kpay_api_base_url, vault, client), repository
                    )
                    checkout_repository = MysqlCheckoutRepository(settings.database_url)
                    await checkout_repository.initialize()
                    app.state.checkout_service = CheckoutService(
                        checkout_repository, KpayVerifier(settings.kpay_api_base_url, vault, client),
                        repository, app.state.payment_service, settings.admin_ids,
                    )
                admin_origin = os.getenv("ADMIN_PUBLIC_ORIGIN", "").strip().rstrip("/")
                parsed_origin = urlsplit(admin_origin)
                if (
                    admin_origin and parsed_origin.scheme == "https" and parsed_origin.hostname
                    and not parsed_origin.path and not parsed_origin.query and not parsed_origin.fragment
                    and not parsed_origin.username and not parsed_origin.password
                ):
                    admin_repository = MysqlAdminWebRepository(settings.database_url)
                    admin_dashboard_repository = MysqlDashboardRepository(settings.database_url)
                    admin_subscription_repository = MysqlSubscriptionRepository(settings.database_url)
                    pricing_repository = MysqlPricingRepository(settings.database_url)
                    await admin_repository.initialize()
                    await admin_subscription_repository.initialize()
                    await pricing_repository.initialize()
                    app.state.admin_public_origin = admin_origin
                    app.state.admin_web_service = AdminWebService(
                        admin_repository, DashboardService(admin_dashboard_repository),
                        AdminPlanService(admin_subscription_repository, settings.admin_ids),
                        BrandingService(admin_subscription_repository),
                        PricingService(pricing_repository),
                    )
                if settings.credential_encryption_key and access_service is None:
                    access_repository = MysqlAccessRepository(
                        settings.database_url, settings.credential_encryption_key
                    )
                    await access_repository.initialize()
                    app.state.access_service = AccessService(access_repository)
                    if settings.node_socket_path:
                        node_client = XrayNodeClient(settings.node_socket_path)
                        app.state.access_service.node_links = node_client.hysteria_link
                        app.state.private_node = node_client
            except ConfigurationError:
                pass
        try:
            yield
        finally:
            if node_client is not None:
                await node_client.close()
            if client is not None:
                await client.aclose()
            if vault is not None:
                await vault.close()
            if repository is not None:
                await repository.close()
            if checkout_repository is not None:
                await checkout_repository.close()
            if access_repository is not None:
                await access_repository.close()
            if admin_subscription_repository is not None:
                await admin_subscription_repository.close()
            if admin_dashboard_repository is not None:
                await admin_dashboard_repository.close()
            if admin_repository is not None:
                await admin_repository.close()
            if pricing_repository is not None:
                await pricing_repository.close()

    framework = FrameworkSettings.model_validate(
        {
            "fastapi": {
                "title": "Papilio VPN API",
                "description": "Subscription status and payment callback",
                "version": "0.1.0",
            },
            "storage": {
                "path": "/tmp/papilio/media",
                "temp_dir": "/tmp/papilio/tmp",
                "max_file_size": 1,
                "allowed_extensions": [],
            },
            "logging": {"level": "INFO", "format": "console", "service": "papilio-vpn"},
        }
    )
    app = create_papilio_app(
        framework,
        routers=[build_payment_router(), build_subscription_router(), build_admin_web_router()],
        middleware=(),
        docs_url=None,
        lifespan=lifespan,
    )
    app.state.payment_service = service
    app.state.checkout_service = None
    app.state.private_node = None
    app.state.access_service = access_service
    app.state.subscription_public_base_url = None
    username = os.getenv("TELEGRAM_BOT_USERNAME", "")
    app.state.bot_return_url = f"https://t.me/{username}" if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) else None
    app.state.admin_web_service = None
    app.state.admin_public_origin = None
    app.mount("/admin/assets", StaticFiles(directory=ADMIN_ASSETS), name="admin-assets")
    app.mount("/subscription-assets", StaticFiles(directory=SUBSCRIPTION_ASSETS), name="subscription-assets")

    @app.middleware("http")
    async def admin_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/admin"):
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'"
            )
        return response

    return app


app = create_app()
