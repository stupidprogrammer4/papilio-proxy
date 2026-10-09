from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.billing.sms_devices.domain.dtos import (
    SmsDeviceRevision,
    SmsDeviceSearch,
    SmsDeviceWrite,
)
from src.modules.billing.sms_devices.domain.results import (
    SmsDeviceEnrollment,
    SmsDeviceRead,
)
from src.modules.billing.sms_devices.interfaces import ISmsDeviceService

router = APIRouter(
    prefix="/v1/admin/payments/sms-devices",
    tags=["SMS Devices"],
    route_class=DishkaRoute,
)


@router.get("", dependencies=[scoped("payments", "read")])
async def page(
    data: Annotated[SmsDeviceSearch, Query()],
    service: FromDishka[ISmsDeviceService],
) -> APIResponse[SmsDeviceRead, BaseMeta]:
    """Page enrolled SMS senders without their keys."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("", dependencies=[scoped("payments", "create")])
async def create(
    data: SmsDeviceWrite, service: FromDishka[ISmsDeviceService]
) -> APIResponse[SmsDeviceEnrollment, None]:
    """Enroll a device and reveal its new key once."""
    result = await service.create(data)
    return APIResponse.from_data(result)


@router.put("/{id:int}", dependencies=[scoped("payments", "update")])
async def update(
    id: int, data: SmsDeviceWrite, service: FromDishka[ISmsDeviceService]
) -> APIResponse[SmsDeviceRead, None]:
    """Change senders, expiry or revoke the selected device."""
    result = await service.update(id, data)
    return APIResponse.from_data(result)


@router.post("/{id:int}/rotate", dependencies=[scoped("payments", "update")])
async def rotate(
    id: int, data: SmsDeviceRevision, service: FromDishka[ISmsDeviceService]
) -> APIResponse[SmsDeviceEnrollment, None]:
    """Rotate the selected device's signing key."""
    result = await service.rotate(id, data.expected_revision)
    return APIResponse.from_data(result)


@router.get("/{id:int}", dependencies=[scoped("payments", "read")])
async def detail(
    id: int, service: FromDishka[ISmsDeviceService]
) -> APIResponse[SmsDeviceRead, None]:
    result = await service.get(id)
    return APIResponse.from_data(result)
