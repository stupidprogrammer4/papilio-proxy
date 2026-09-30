from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from bot.core.config import ConfigurationError, Settings
from bot.infra.db.credentials import MysqlCredentialVault
from bot.infra.kpay import KpayVerifier
from bot.presentation.payment_callback import build_payment_router
from bot.services.payments import PaymentVerificationService


def create_app(service: PaymentVerificationService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        vault: MysqlCredentialVault | None = None
        client: httpx.AsyncClient | None = None
        if service is None:
            try:
                settings = Settings.from_environment(require_token=False)
                if settings.kpay_api_base_url and settings.credential_encryption_key:
                    vault = MysqlCredentialVault(
                        settings.database_url, settings.credential_encryption_key
                    )
                    client = httpx.AsyncClient(timeout=10.0, follow_redirects=False)
                    app.state.payment_service = PaymentVerificationService(
                        KpayVerifier(settings.kpay_api_base_url, vault, client)
                    )
            except ConfigurationError:
                pass
        try:
            yield
        finally:
            if client is not None:
                await client.aclose()
            if vault is not None:
                await vault.close()

    app = FastAPI(lifespan=lifespan)
    app.state.payment_service = service
    app.include_router(build_payment_router())
    return app


app = create_app()
