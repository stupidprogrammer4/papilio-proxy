from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import CurrentStaff, scoped
from src.modules.operations.notifications.domain.dtos import (
    AdminNotificationSearch,
    ManualNotificationCreate,
    NotificationRecovery,
    NotificationSearch,
)
from src.modules.operations.notifications.interfaces import (
    INotificationAttemptQuery,
    INotificationCreateCommand,
    INotificationDeliveryCommand,
    INotificationPolicyQuery,
    INotificationQuery,
    INotificationRecoveryQuery,
)
from src.modules.operations.notifications.routers.schemas import (
    AdminNotificationCreate,
    AdminNotificationOut,
    NotificationAttemptOut,
    NotificationPolicyOut,
    NotificationQueuedOut,
    NotificationRecoveryOut,
)
from src.modules.operations.notifications.tasks.schedulers.delivery import (
    DeliverNotification,
)

router = APIRouter(
    prefix="/v1/admin/notifications",
    tags=["Admin Notifications"],
    route_class=DishkaRoute,
)


@router.get("/policy", dependencies=[scoped("notifications")])
async def policy(
    service: FromDishka[INotificationPolicyQuery],
) -> APIResponse[NotificationPolicyOut, None]:
    """Read delivery policy and operational availability."""
    result = await service.current()
    return APIResponse.from_data(
        NotificationPolicyOut(
            **result.values.model_dump(),
            capacity_valid=result.capacity_valid,
            outbound_available=result.outbound_available,
            supported_kinds=list(result.supported_kinds),
        )
    )


@router.get("", dependencies=[scoped("notifications")])
async def search(
    data: Annotated[AdminNotificationSearch, Query()],
    service: FromDishka[INotificationQuery],
) -> APIResponse[AdminNotificationOut, BaseMeta]:
    """Search customer notices and delivery states."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[
            AdminNotificationOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("", dependencies=[scoped("notifications")])
async def create(
    data: AdminNotificationCreate,
    principal: CurrentStaff,
    command: FromDishka[INotificationCreateCommand],
) -> APIResponse[AdminNotificationOut, None]:
    """Create a replay-safe notice for a known customer."""
    row = await command.manual(
        data.customer_id,
        ManualNotificationCreate.model_validate(data.model_dump()),
        principal.staff_id,
    )
    return APIResponse.from_data(
        AdminNotificationOut.model_validate(row, from_attributes=True)
    )


@router.get("/{id:int}", dependencies=[scoped("notifications")])
async def detail(
    id: int, service: FromDishka[INotificationQuery]
) -> APIResponse[AdminNotificationOut, None]:
    """Inspect one actual delivery record."""
    row = await service.get(id)
    return APIResponse.from_data(
        AdminNotificationOut.model_validate(row, from_attributes=True)
    )


@router.put(
    "/{id:int}/recovery", dependencies=[scoped("notifications", "update")]
)
async def recover(
    id: int,
    data: NotificationRecovery,
    principal: CurrentStaff,
    command: FromDishka[INotificationDeliveryCommand],
) -> APIResponse[AdminNotificationOut, None]:
    """Retry or cancel an eligible notice with an audited reason."""
    row = await command.recover(id, principal.staff_id, data)
    return APIResponse.from_data(
        AdminNotificationOut.model_validate(row, from_attributes=True)
    )


@router.post(
    "/{id:int}/dispatch",
    status_code=202,
    dependencies=[scoped("notifications", "update")],
)
async def dispatch(
    id: int, service: FromDishka[INotificationQuery]
) -> APIResponse[NotificationQueuedOut, None]:
    """Queue one notice; the delivery policy remains decisive."""
    await service.get(id)
    await DeliverNotification.enqueue(notification_id=id)
    return APIResponse.from_data(NotificationQueuedOut(notification_id=id))


@router.get("/{id:int}/attempts", dependencies=[scoped("notifications")])
async def attempts(
    id: int,
    data: Annotated[NotificationSearch, Query()],
    tickets: FromDishka[INotificationQuery],
    service: FromDishka[INotificationAttemptQuery],
) -> APIResponse[NotificationAttemptOut, BaseMeta]:
    """Page through attempts without exposing lease credentials."""
    await tickets.get(id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[
            NotificationAttemptOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}/history", dependencies=[scoped("notifications")])
async def history(
    id: int,
    data: Annotated[NotificationSearch, Query()],
    tickets: FromDishka[INotificationQuery],
    service: FromDishka[INotificationRecoveryQuery],
) -> APIResponse[NotificationRecoveryOut, BaseMeta]:
    """Page through immutable operator recovery decisions."""
    await tickets.get(id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[
            NotificationRecoveryOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
