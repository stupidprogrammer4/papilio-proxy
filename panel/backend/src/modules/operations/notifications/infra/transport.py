import asyncio
from typing import Literal

import aiohttp
from pydantic import BaseModel, Field, ValidationError, model_validator

from src.config.settings import PapilioSettings
from src.modules.operations.notifications.domain.results import (
    DeliveryOutcome,
    NotificationClaim,
)


class AdapterOutcome(BaseModel):
    outcome: Literal["accepted", "retryable", "ambiguous", "rejected"]
    error_code: str | None = Field(
        default=None, max_length=64, pattern=r"^[a-z0-9_]+$"
    )
    message_id: int | None = Field(default=None, gt=0)
    retry_after_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def accepted_message(self) -> "AdapterOutcome":
        if self.outcome == "accepted" and self.message_id is None:
            raise ValueError(
                "An accepted delivery requires its message identity"
            )
        return self


class AiogramNotificationTransport:
    def __init__(
        self, settings: PapilioSettings, session: aiohttp.ClientSession
    ) -> None:
        self.settings, self.session = settings, session

    async def send(self, claim: NotificationClaim) -> DeliveryOutcome:
        c = self.settings.notifications
        if not c.outbound_enabled or not c.endpoint or not c.delivery_key:
            return DeliveryOutcome(
                "retryable", "notification_outbound_disabled"
            )
        try:
            async with self.session.post(
                c.endpoint,
                timeout=aiohttp.ClientTimeout(total=c.timeout_seconds),
                allow_redirects=False,
                headers={
                    "X-Papilio-Delivery-Key": c.delivery_key,
                    "Accept-Encoding": "identity",
                },
                json={
                    "notification_id": claim.notification_id,
                    "claim_token": claim.claim_token,
                },
            ) as response:
                if response.status in {401, 403}:
                    return DeliveryOutcome(
                        "rejected", "notification_adapter_denied"
                    )
                if response.status != 200:
                    return DeliveryOutcome(
                        "ambiguous", "notification_adapter_http"
                    )
                try:
                    payload = await response.content.readexactly(
                        c.max_response_bytes + 1
                    )
                except asyncio.IncompleteReadError as error:
                    payload = error.partial
                if (
                    len(payload) > c.max_response_bytes
                    or response.headers.get("Content-Encoding", "identity")
                    != "identity"
                ):
                    return DeliveryOutcome(
                        "ambiguous", "notification_adapter_response"
                    )
                parsed = AdapterOutcome.model_validate_json(payload)
                return DeliveryOutcome(
                    parsed.outcome,
                    parsed.error_code,
                    parsed.message_id,
                    parsed.retry_after_seconds,
                )
        except aiohttp.ClientConnectorError:
            return DeliveryOutcome(
                "retryable", "notification_adapter_unreachable"
            )
        except (aiohttp.ClientError, TimeoutError, OSError):
            return DeliveryOutcome(
                "ambiguous", "notification_adapter_transport"
            )
        except (ValidationError, ValueError):
            return DeliveryOutcome(
                "ambiguous", "notification_adapter_response"
            )
