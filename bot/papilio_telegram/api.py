import asyncio
import json
import math
from typing import Any

import aiohttp

from papilio_telegram.checkout import (
    CheckoutCancel,
    CheckoutCreate,
    CheckoutDestination,
    CheckoutFundingPolicy,
    CheckoutOffer,
    CheckoutPaymentInstruction,
    CheckoutRead,
    CheckoutReconfirm,
    CheckoutRetirement,
)
from papilio_telegram.commerce import (
    CustomerLoyalty,
    CustomerPriceQuote,
    CustomerRenewalEligibility,
    NotificationAuthorization,
    TrialAvailability,
    TrialSubscription,
)
from papilio_telegram.config import BotApiLimits
from papilio_telegram.topups import TopupPaymentInstruction


class BotApiError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BotApi:
    def __init__(
        self,
        base_url: str,
        key: str,
        timeout_seconds: float,
        limits: BotApiLimits,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("API timeout must be finite and positive")
        self.base_url, self.key = base_url.rstrip("/"), key
        self.timeout_seconds, self.limits = timeout_seconds, limits
        self.client: aiohttp.ClientSession | None = None

    def session(self) -> aiohttp.ClientSession:
        if self.client is None or self.client.closed:
            self.client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                connector=aiohttp.TCPConnector(
                    limit=self.limits.max_connections,
                    limit_per_host=self.limits.max_connections,
                    keepalive_timeout=self.limits.keepalive_seconds,
                    ttl_dns_cache=self.limits.dns_cache_seconds,
                ),
                cookie_jar=aiohttp.DummyCookieJar(),
                auto_decompress=False,
                read_bufsize=self.limits.read_buffer_bytes,
                headers={
                    "X-Papilio-Bot-Key": self.key,
                    "Accept-Encoding": "identity",
                },
            )
        return self.client

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None

    async def call(
        self,
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/v1/bot/"):
            raise BotApiError("request_failed")
        try:
            async with self.session().request(
                method, self.base_url + path, json=body, allow_redirects=False
            ) as response:
                if response.headers.get(
                    "Content-Encoding", ""
                ).strip().lower() not in {"", "identity"}:
                    raise BotApiError("response_encoding_unsupported")
                capacity = self.limits.max_response_bytes
                if (
                    response.content_length is not None
                    and response.content_length > capacity
                ):
                    raise BotApiError("response_too_large")
                try:
                    raw = await response.content.readexactly(capacity + 1)
                except asyncio.IncompleteReadError as partial:
                    raw = partial.partial
                if len(raw) > capacity:
                    raise BotApiError("response_too_large")
                payload = await asyncio.to_thread(json.loads, raw)
                status = response.status
        except (
            aiohttp.ClientError,
            TimeoutError,
            ValueError,
            RecursionError,
        ) as exc:
            raise BotApiError("network") from exc
        if not isinstance(payload, dict):
            raise BotApiError("request_failed")
        if not 200 <= status < 300:
            error = payload.get("error", payload)
            code = (
                error.get("message_code") if isinstance(error, dict) else None
            )
            raise BotApiError(
                code if isinstance(code, str) else "request_failed"
            )
        return payload

    async def home(
        self, telegram_id: int, display_name: str
    ) -> dict[str, Any]:
        response = await self.call(
            "/v1/bot/home",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        return response["data"]

    async def plans(
        self, telegram_id: int, display_name: str, page: int = 1
    ) -> dict[str, Any]:
        result = await self.call(
            f"/v1/bot/customer-plans?page={page}",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        return result

    async def subscriptions(
        self, telegram_id: int, display_name: str, page: int = 1
    ) -> dict[str, Any]:
        result = await self.call(
            f"/v1/bot/subscriptions/search?page={page}",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        return result

    async def topup(
        self,
        telegram_id: int,
        display_name: str,
        amount_rial: int,
        request_key: str,
    ) -> dict[str, Any]:
        result = await self.call(
            "/v1/bot/topups",
            "POST",
            {
                "telegram_id": telegram_id,
                "display_name": display_name,
                "amount_rial": amount_rial,
                "request_key": request_key,
            },
        )
        return result["data"]

    async def topup_instruction(
        self, id: int, telegram_id: int, display_name: str
    ) -> TopupPaymentInstruction | None:
        response = await self.call(
            f"/v1/bot/topups/{id}/payment-instruction",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:
            data = response["data"]
            result = (
                None
                if data is None
                else await asyncio.to_thread(
                    TopupPaymentInstruction.model_validate, data
                )
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def purchase(
        self,
        telegram_id: int,
        display_name: str,
        plan_id: int,
        auto_renew: bool,
        purchase_key: str,
        expected_price_rial: int | None = None,
    ) -> dict[str, Any]:
        result = await self.call(
            "/v1/bot/purchase",
            "POST",
            {
                "telegram_id": telegram_id,
                "display_name": display_name,
                "plan_id": plan_id,
                "auto_renew": auto_renew,
                "purchase_key": purchase_key,
                "expected_price_rial": expected_price_rial,
            },
        )
        return result["data"]

    async def auto_renew(
        self,
        telegram_id: int,
        display_name: str,
        subscription_id: int,
        enabled: bool,
    ) -> dict[str, Any]:
        result = await self.call(
            f"/v1/bot/subscriptions/{subscription_id}/auto-renew",
            "PATCH",
            {
                "telegram_id": telegram_id,
                "display_name": display_name,
                "enabled": enabled,
            },
        )
        return result["data"]

    async def delivery(
        self,
        telegram_id: int,
        display_name: str,
        subscription_id: int,
        rotate: bool = False,
    ) -> dict[str, Any]:
        action = "rotate-link" if rotate else "delivery"
        result = await self.call(
            f"/v1/bot/subscriptions/{subscription_id}/{action}",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        return result["data"]

    async def account_link(
        self, telegram_id: int, display_name: str
    ) -> dict[str, Any]:
        response = await self.call(
            "/v1/bot/account-link",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        return response["data"]

    async def plan(
        self, id: int, telegram_id: int, display_name: str
    ) -> dict[str, Any]:
        response = await self.call(
            f"/v1/bot/customer-plans/{id}",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        return response["data"]

    async def support_link(
        self, telegram_id: int, display_name: str
    ) -> dict[str, Any]:
        result = await self.call(
            "/v1/bot/support-link",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        return result["data"]

    async def authorize_notification(
        self, id: int, claim_token: str
    ) -> NotificationAuthorization:
        response = await self.call(
            f"/v1/bot/notifications/{id}/authorize",
            "POST",
            {"claim_token": claim_token},
        )
        try:
            result = await asyncio.to_thread(
                NotificationAuthorization.model_validate, response["data"]
            )
        except (KeyError, ValueError):
            raise BotApiError("request_failed") from None
        return result

    async def renewal_eligibility(
        self, telegram_id: int, display_name: str, subscription_id: int
    ) -> CustomerRenewalEligibility:
        response = await self.call(
            f"/v1/bot/subscriptions/{subscription_id}/renewal-eligibility",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:
            result = await asyncio.to_thread(
                CustomerRenewalEligibility.model_validate, response["data"]
            )
        except (KeyError, ValueError):
            raise BotApiError("request_failed") from None
        return result

    async def trial_availability(
        self, telegram_id: int, display_name: str
    ) -> TrialAvailability:
        result = await self.call(
            "/v1/bot/trials/availability",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:
            offer = await asyncio.to_thread(
                TrialAvailability.model_validate, result["data"]
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return offer

    async def trial_claim(
        self, telegram_id: int, display_name: str, request_key: str
    ) -> TrialSubscription:
        result = await self.call(
            "/v1/bot/trials",
            "POST",
            {
                "telegram_id": telegram_id,
                "display_name": display_name,
                "request_key": request_key,
            },
        )
        try:
            subscription = await asyncio.to_thread(
                TrialSubscription.model_validate, result["data"]
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return subscription

    async def loyalty(
        self, telegram_id: int, display_name: str
    ) -> CustomerLoyalty:
        response = await self.call(
            "/v1/bot/loyalty",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:
            result = await asyncio.to_thread(
                CustomerLoyalty.model_validate, response["data"]
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def price_quote(
        self, plan_id: int, telegram_id: int, display_name: str
    ) -> CustomerPriceQuote:
        response = await self.call(
            f"/v1/bot/customer-plans/{plan_id}/quote",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:
            result = await asyncio.to_thread(
                CustomerPriceQuote.model_validate, response["data"]
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def checkout_offer(
        self, plan_id: int, telegram_id: int, display_name: str
    ) -> CheckoutOffer:
        response = await self.call(
            f"/v1/bot/checkouts/offers/{plan_id}",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:
            result = await asyncio.to_thread(
                CheckoutOffer.model_validate, response["data"]
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def _checkout(
        self,
        path: str,
        telegram_id: int,
        display_name: str,
        body: dict[str, Any] | None = None,
    ) -> CheckoutRead:
        response = await self.call(
            path,
            "POST",
            {
                **(body or {}),
                "telegram_id": telegram_id,
                "display_name": display_name,
            },
        )
        try:
            result = await asyncio.to_thread(
                CheckoutRead.model_validate, response["data"]
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def checkout_lookup(
        self, telegram_id: int, display_name: str, request_key: str
    ) -> CheckoutRead | None:
        try:
            response = await self.call(
                "/v1/bot/checkouts/lookup",
                "POST",
                {
                    "telegram_id": telegram_id,
                    "display_name": display_name,
                    "request_key": request_key,
                },
            )
        except BotApiError as exc:
            if exc.code == "checkout_not_found":
                return None
            raise
        try:
            data = response["data"]
            result = (
                None
                if data is None
                else await asyncio.to_thread(CheckoutRead.model_validate, data)
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def checkout_history(
        self,
        telegram_id: int,
        display_name: str,
        page: int,
        per_page: int,
    ) -> tuple[list[CheckoutRead], int]:
        response = await self.call(
            f"/v1/bot/checkouts/history?page={page}&per_page={per_page}",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:

            def parse() -> tuple[list[CheckoutRead], int]:
                rows = [
                    CheckoutRead.model_validate(row)
                    for row in response["data"]
                ]
                pages = int(response["meta"]["pager"]["total_pages"])
                return rows, pages

            result = await asyncio.to_thread(parse)
        except (KeyError, ValueError, TypeError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def checkout_create(
        self,
        telegram_id: int,
        display_name: str,
        body: CheckoutCreate,
    ) -> CheckoutRead:
        result = await self._checkout(
            "/v1/bot/checkouts",
            telegram_id,
            display_name,
            body.model_dump(),
        )
        return result

    async def checkout_status(
        self,
        checkout_id: int,
        telegram_id: int,
        display_name: str,
    ) -> CheckoutRead:
        result = await self._checkout(
            f"/v1/bot/checkouts/{checkout_id}/status",
            telegram_id,
            display_name,
        )
        return result

    async def checkout_reconfirm(
        self,
        checkout_id: int,
        telegram_id: int,
        display_name: str,
        body: CheckoutReconfirm,
    ) -> CheckoutRead:
        result = await self._checkout(
            f"/v1/bot/checkouts/{checkout_id}/reconfirm",
            telegram_id,
            display_name,
            body.model_dump(),
        )
        return result

    async def checkout_cancel(
        self,
        checkout_id: int,
        telegram_id: int,
        display_name: str,
        body: CheckoutCancel,
    ) -> CheckoutRead:
        result = await self._checkout(
            f"/v1/bot/checkouts/{checkout_id}/cancel",
            telegram_id,
            display_name,
            body.model_dump(),
        )
        return result

    async def checkout_funding(
        self,
        telegram_id: int,
        display_name: str,
    ) -> CheckoutFundingPolicy:
        response = await self.call(
            "/v1/bot/checkouts/funding",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:
            result = await asyncio.to_thread(
                CheckoutFundingPolicy.model_validate, response["data"]
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def checkout_destinations(
        self,
        telegram_id: int,
        display_name: str,
        page: int,
        per_page: int,
    ) -> tuple[list[CheckoutDestination], int]:
        response = await self.call(
            f"/v1/bot/checkouts/destinations?page={page}&per_page={per_page}",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:

            def parse() -> tuple[list[CheckoutDestination], int]:
                rows = [
                    CheckoutDestination.model_validate(row)
                    for row in response["data"]
                ]
                pages = int(response["meta"]["pager"]["total_pages"])
                return rows, pages

            result = await asyncio.to_thread(parse)
        except (KeyError, ValueError, TypeError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def checkout_payment_instruction(
        self,
        checkout_id: int,
        telegram_id: int,
        display_name: str,
    ) -> CheckoutPaymentInstruction | None:
        response = await self.call(
            f"/v1/bot/checkouts/{checkout_id}/payment-instruction",
            "POST",
            {"telegram_id": telegram_id, "display_name": display_name},
        )
        try:
            data = response["data"]
            result = (
                None
                if data is None
                else await asyncio.to_thread(
                    CheckoutPaymentInstruction.model_validate, data
                )
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        return result

    async def checkout_retire(
        self,
        telegram_id: int,
        display_name: str,
        request_key: str,
    ) -> CheckoutRetirement:
        response = await self.call(
            "/v1/bot/checkouts/retire",
            "POST",
            {
                "telegram_id": telegram_id,
                "display_name": display_name,
                "request_key": request_key,
            },
        )
        try:
            result = await asyncio.to_thread(
                CheckoutRetirement.model_validate, response["data"]
            )
        except (KeyError, ValueError) as exc:
            raise BotApiError("request_failed") from exc
        if result.request_key != request_key:
            raise BotApiError("request_failed")
        return result
