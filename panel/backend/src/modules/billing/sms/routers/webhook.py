import asyncio
import hashlib
import hmac
import time

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from papilio.security.crypto import secure_compare
from pydantic import TypeAdapter, ValidationError

from src.config.settings import PapilioSettings
from src.modules.billing.sms.domain.dtos import SmsReceived
from src.modules.billing.sms.interfaces import ISmsService

router = APIRouter(
    prefix="/v1/webhooks/sms", tags=["SMS Webhook"], route_class=DishkaRoute
)


@router.post("")
async def receive(
    request: Request,
    service: FromDishka[ISmsService],
    settings: FromDishka[PapilioSettings],
) -> dict[str, bool]:
    """Accept a signed bank-message observation from the owner's phone."""
    timestamp = request.headers.get("X-Papilio-Timestamp", "")
    signature = request.headers.get("X-Papilio-Signature", "")
    if (
        not timestamp.isascii()
        or len(timestamp) > 20
        or not timestamp.isdecimal()
        or abs(time.time() - int(timestamp))
        > settings.operations.sms_clock_skew_seconds
    ):
        raise HTTPException(401, "امضای پیامک معتبر نیست.")
    raw = await request.body()
    mac = await asyncio.to_thread(
        hmac.new,
        settings.security.sms_webhook_key.encode(),
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    )
    expected = mac.hexdigest()
    if not signature.isascii() or not secure_compare(expected, signature):
        raise HTTPException(401, "امضای پیامک معتبر نیست.")
    try:
        data = TypeAdapter(SmsReceived).validate_json(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_input=False)) from None
    await service.receive(data)
    return {"accepted": True}
