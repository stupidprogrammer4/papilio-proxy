from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.customer_auth.config.dependencies import (
    CurrentCustomer,
    WritableCustomer,
)
from src.modules.operations.notifications.domain.dtos import (
    NotificationRead,
    NotificationSearch,
)
from src.modules.operations.notifications.interfaces import (
    INotificationInboxCommand,
    INotificationQuery,
)
from src.modules.operations.notifications.routers.schemas import (
    NotificationOut,
)

router = APIRouter(
    prefix="/v1/customer/notifications",
    tags=["Customer Notifications"],
    route_class=DishkaRoute,
)


@router.get("")
async def search(
    data: Annotated[NotificationSearch, Query()],
    principal: CurrentCustomer,
    service: FromDishka[INotificationQuery],
) -> APIResponse[NotificationOut, BaseMeta]:
    """Page through this customer's inbox."""
    result = await service.search_customer(principal.customer_id, data)
    return APIResponse(
        success=True,
        data=[
            NotificationOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}")
async def detail(
    id: int,
    principal: CurrentCustomer,
    service: FromDishka[INotificationQuery],
) -> APIResponse[NotificationOut, None]:
    """Read an owned inbox notice."""
    row = await service.get_for_customer(id, principal.customer_id)
    return APIResponse.from_data(
        NotificationOut.model_validate(row, from_attributes=True)
    )


@router.put("/{id:int}/read")
async def set_read(
    id: int,
    data: NotificationRead,
    principal: WritableCustomer,
    command: FromDishka[INotificationInboxCommand],
) -> APIResponse[NotificationOut, None]:
    """Mark one owned inbox notice read or unread."""
    row = await command.set_read(id, principal.customer_id, data.is_read)
    return APIResponse.from_data(
        NotificationOut.model_validate(row, from_attributes=True)
    )
