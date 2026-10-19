from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError

from src.modules.billing.sms.domain.dtos import SmsReceived
from src.modules.billing.sms.interfaces import ISmsService
from src.modules.billing.sms_devices.domain.dtos import SmsDeviceStatusReport
from src.modules.billing.sms_devices.interfaces import (
    ISmsDeviceService,
    ISmsSettlementCommand,
)
from src.modules.sales.checkout.interfaces import ICheckoutFundingPublisher

router = APIRouter(
    prefix="/v1/webhooks/sms-devices",
    tags=["Device SMS Webhook"],
    route_class=DishkaRoute,
)


@router.post("/{id:int}")
async def receive(
    id: int,
    request: Request,
    devices: FromDishka[ISmsDeviceService],
    sms: FromDishka[ISmsService],
    settlement: FromDishka[ISmsSettlementCommand],
    publisher: FromDishka[ICheckoutFundingPublisher],
) -> dict[str, bool]:
    """Accept a signed observation from one enrolled bank sender."""
    raw = await request.body()
    try:
        data = TypeAdapter(SmsReceived).validate_json(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_input=False)) from None
    await devices.verify(
        id,
        request.headers.get("X-Papilio-Timestamp", ""),
        request.headers.get("X-Papilio-Signature", ""),
        raw,
        data,
    )
    await sms.receive(data, device_id=id)
    await settlement.check_event(data.event_id)
    # Settlement and the current provenance read have committed before queue
    # publication. Only an actual SMS-approved topup can fund an owned intent.
    topup_id = await settlement.approved_topup_for_event(data.event_id, id)
    if topup_id is not None:
        await publisher.publish(topup_id)
    return {"accepted": True}


@router.post("/{id:int}/status")
async def report_status(
    id: int,
    request: Request,
    devices: FromDishka[ISmsDeviceService],
) -> dict[str, bool]:
    """Store a signed, bounded device delivery and permission snapshot."""
    raw = await request.body()
    try:
        data = TypeAdapter(SmsDeviceStatusReport).validate_json(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_input=False)) from None
    await devices.report_status(
        id,
        request.headers.get("X-Papilio-Timestamp", ""),
        request.headers.get("X-Papilio-Signature", ""),
        raw,
        data,
    )
    return {"accepted": True}
