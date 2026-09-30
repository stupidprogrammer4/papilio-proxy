from __future__ import annotations

from collections.abc import Mapping

import httpx
from sqlalchemy.exc import SQLAlchemyError

from bot.infra.db.credentials import KPAY_ACCESS_TOKEN_NAME, MysqlCredentialVault
from bot.models.credentials import CredentialStorageError
from bot.models.payments import PaymentProviderUnavailable, ProviderVerification


class KpayVerifier:
    def __init__(
        self, base_url: str, vault: MysqlCredentialVault, client: httpx.AsyncClient
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._vault = vault
        self._client = client

    async def verify(self, authority: str) -> ProviderVerification:
        try:
            token = await self._vault.get(KPAY_ACCESS_TOKEN_NAME)
            if not token:
                token = await self._login()
            response = await self._verify_request(authority, token)
            if response.status_code == 401:
                token = await self._login()
                response = await self._verify_request(authority, token)
            if response.status_code != 200:
                raise PaymentProviderUnavailable("KPay verification failed")
            payload = response.json()
        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
            CredentialStorageError,
            SQLAlchemyError,
        ) as exc:
            raise PaymentProviderUnavailable("KPay verification unavailable") from exc
        if not isinstance(payload, Mapping):
            raise PaymentProviderUnavailable("Invalid KPay verification response")
        transaction_id = payload.get("id")
        returned_authority = payload.get("authority")
        status = payload.get("status")
        amount = payload.get("amount")
        paid_at = payload.get("paid_at")
        if (
            not isinstance(transaction_id, str)
            or not transaction_id
            or returned_authority != authority
            or not isinstance(status, str)
            or not status
            or isinstance(amount, bool)
            or not isinstance(amount, int)
            or amount <= 0
            or (paid_at is not None and (not isinstance(paid_at, str) or not paid_at))
        ):
            raise PaymentProviderUnavailable("Invalid KPay verification response")
        return ProviderVerification(authority, status, transaction_id, amount, paid_at)

    async def _verify_request(self, authority: str, token: str) -> httpx.Response:
        return await self._client.post(
            f"{self._base_url}/transactions/verify",
            json={"authority": authority},
            headers={"Authorization": f"Bearer {token}"},
        )

    async def _login(self) -> str:
        credentials = await self._vault.load_kpay_credentials()
        if credentials is None:
            raise PaymentProviderUnavailable("KPay credentials unavailable")
        response = await self._client.post(
            f"{self._base_url}/auth/login",
            data={"username": credentials.username, "password": credentials.password},
        )
        if response.status_code != 200:
            raise PaymentProviderUnavailable("KPay login failed")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise PaymentProviderUnavailable("Invalid KPay login response")
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not isinstance(access_token, str) or not access_token:
            raise PaymentProviderUnavailable("Invalid KPay login response")
        if refresh_token is not None and not isinstance(refresh_token, str):
            raise PaymentProviderUnavailable("Invalid KPay login response")
        await self._vault.save_kpay_tokens(access_token, refresh_token)
        return access_token
