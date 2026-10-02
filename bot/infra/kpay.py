from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy.exc import SQLAlchemyError

from bot.infra.db.credentials import KPAY_ACCESS_TOKEN_NAME, MysqlCredentialVault
from bot.models.credentials import CredentialStorageError
from bot.models.payments import PaymentInitiation, PaymentProviderUnavailable, ProviderVerification
from bot.models.receipts import ReceiptPaymentPage


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

    async def create_transaction(
        self,
        *,
        shop_id: str,
        card_id: str,
        amount_rial: int,
        callback_url: str,
        order_id: str,
        description: str,
    ) -> PaymentInitiation:
        """Create a KPay checkout for one already-persisted order."""
        try:
            UUID(shop_id)
            UUID(card_id)
        except ValueError as exc:
            raise PaymentProviderUnavailable("Invalid KPay shop or card ID") from exc
        callback = urlsplit(callback_url)
        if (
            callback.scheme != "https"
            or not callback.hostname
            or callback.username
            or callback.password
            or not callback.path.endswith("/payments/kpay/callback")
            or amount_rial <= 0
            or not order_id
        ):
            raise PaymentProviderUnavailable("Invalid KPay checkout parameters")
        payload = {
            "shop_id": shop_id,
            "card_id": card_id,
            "amount": amount_rial,
            "callback_url": callback_url,
            "factor_number": order_id,
            "description": description[:200],
            "fee_side": "seller",
        }
        try:
            token = await self._vault.get(KPAY_ACCESS_TOKEN_NAME)
            if not token:
                token = await self._login()
            response = await self._client.post(
                f"{self._base_url}/transactions/create",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == 401:
                token = await self._login()
                response = await self._client.post(
                    f"{self._base_url}/transactions/create",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code not in {200, 201}:
                raise PaymentProviderUnavailable("KPay checkout failed")
            data = response.json()
        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
            CredentialStorageError,
            SQLAlchemyError,
        ) as exc:
            raise PaymentProviderUnavailable("KPay checkout unavailable") from exc
        if not isinstance(data, Mapping):
            raise PaymentProviderUnavailable("Invalid KPay checkout response")
        transaction_id = data.get("id")
        authority = data.get("authority")
        returned_amount = data.get("amount")
        payment_url = data.get("payment_url")
        status = data.get("status")
        if (
            status != "pending"
            or not isinstance(transaction_id, str)
            or not transaction_id
            or not isinstance(authority, str)
            or not authority
            or isinstance(returned_amount, bool)
            or returned_amount != amount_rial
        ):
            raise PaymentProviderUnavailable("Invalid KPay checkout response")
        if payment_url is None:
            # The live card-to-card API currently omits payment_url despite its docs.
            # Confirm the public transaction record before constructing its hosted page.
            if (
                urlsplit(self._base_url).hostname != "kpay.website"
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", authority) is None
            ):
                raise PaymentProviderUnavailable("Cannot verify KPay hosted payment page")
            try:
                info_response = await self._client.get(
                    f"{self._base_url}/transactions/payment/{authority}"
                )
                info = info_response.json()
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                raise PaymentProviderUnavailable("KPay hosted payment page unavailable") from exc
            if (
                info_response.status_code != 200
                or not isinstance(info, Mapping)
                or info.get("authority") != authority
                or info.get("amount") != amount_rial
                or info.get("status") != "pending"
            ):
                raise PaymentProviderUnavailable("KPay hosted payment page did not match")
            payment_url = f"https://kpay.website/pay/{authority}"
        if not isinstance(payment_url, str):
            raise PaymentProviderUnavailable("Invalid KPay checkout URL")
        payment = urlsplit(payment_url)
        if (
            payment.scheme != "https"
            or payment.hostname not in {"kpay.website", "www.kpay.website"}
            or payment.username
            or payment.password
        ):
            raise PaymentProviderUnavailable("Unsafe KPay payment URL")
        return PaymentInitiation(transaction_id, authority, amount_rial, payment_url)

    async def _verify_request(self, authority: str, token: str) -> httpx.Response:
        return await self._client.post(
            f"{self._base_url}/transactions/verify",
            json={"authority": authority},
            headers={"Authorization": f"Bearer {token}"},
        )

    async def payment_page(self, authority: str) -> ReceiptPaymentPage:
        try:
            response = await self._client.get(
                f"{self._base_url}/transactions/payment/{authority}"
            )
            data = response.json()
            if response.status_code != 200 or not isinstance(data, Mapping):
                raise PaymentProviderUnavailable("KPay payment page unavailable")
            if data.get("authority") != authority:
                raise PaymentProviderUnavailable("KPay page authority mismatch")
            amount, final, remaining = (
                data.get("amount"), data.get("final_amount"), data.get("remaining_seconds"),
            )
            card, owner, status = data.get("card_number"), data.get("owner_name"), data.get("status")
            if (any(type(value) is not int for value in (amount, final, remaining))
                    or not isinstance(amount, int) or not isinstance(final, int)
                    or not isinstance(remaining, int) or amount <= 0 or final < amount
                    or not isinstance(card, str) or re.fullmatch(r"[0-9]{16}", card) is None
                    or not isinstance(owner, str) or not isinstance(status, str)):
                raise PaymentProviderUnavailable("Invalid KPay payment page")
            return ReceiptPaymentPage(amount, final, card, owner, remaining, status)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise PaymentProviderUnavailable("KPay payment page unavailable") from exc

    async def upload_receipt(self, authority: str, image: str) -> None:
        try:
            response = await self._client.post(
                f"{self._base_url}/transactions/payment/{authority}/upload-receipt",
                json={"receipt_image": image},
            )
            # Keep the provider's actual response encrypted for the private pilot.
            # Never emit image data, banking identifiers or authority to logs.
            try:
                payload = response.json()
            except ValueError:
                payload = {"content_type": response.headers.get("content-type", ""), "not_json": True}
            observation = json.dumps({"http_status": response.status_code, "body": payload}, ensure_ascii=False)
            if len(observation.encode()) > 2_000:
                observation = json.dumps({
                    "http_status": response.status_code,
                    "response_field_names": [str(key)[:40] for key in list(payload)[:20]] if isinstance(payload, Mapping) else [],
                    "oversized": True,
                }, ensure_ascii=True)
                if len(observation) > 2_000:
                    observation = '{"oversized": true}'
            await self._vault.put(
                "kpay.receipt_response." + hashlib.sha256(authority.encode()).hexdigest(), observation,
            )
            if response.status_code not in {200, 201}:
                raise PaymentProviderUnavailable("KPay receipt upload unavailable")
        except (httpx.HTTPError, ValueError, TypeError, CredentialStorageError, SQLAlchemyError) as exc:
            raise PaymentProviderUnavailable("KPay receipt upload unavailable") from exc

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
