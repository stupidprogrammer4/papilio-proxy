from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal
from src.modules.support.domain.dtos import (
    ThreadSearch,
    TicketCreate,
    TicketReply,
    TicketSearch,
    TicketStateWrite,
)
from src.modules.support.interfaces import (
    ISupportCreateCommand,
    ISupportHistoryQuery,
    ISupportMessageQuery,
    ISupportPolicyQuery,
    ISupportThreadCommand,
    ISupportTicketQuery,
)
from src.modules.support.routers.schemas import (
    AdminSupportHistoryOut,
    AdminSupportMessageOut,
    AdminTicketCreate,
    SupportPolicyOut,
    SupportTicketOut,
)

router = APIRouter(
    prefix="/v1/admin/support", tags=["Admin Support"], route_class=DishkaRoute
)


@router.get("/policy", dependencies=[scoped("support")])
async def policy(
    service: FromDishka[ISupportPolicyQuery],
) -> APIResponse[SupportPolicyOut, None]:
    """Read current support permissions and capacities."""
    result = await service.current()
    return APIResponse.from_data(
        SupportPolicyOut(
            **result.values.model_dump(), capacity_valid=result.capacity_valid
        )
    )


@router.get("", dependencies=[scoped("support")])
async def search(
    data: Annotated[TicketSearch, Query()],
    service: FromDishka[ISupportTicketQuery],
) -> APIResponse[SupportTicketOut, BaseMeta]:
    """Search support tickets and their customer context."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[
            SupportTicketOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}", dependencies=[scoped("support")])
async def detail(
    id: int, service: FromDishka[ISupportTicketQuery]
) -> APIResponse[SupportTicketOut, None]:
    """Read the selected ticket."""
    result = await service.get(id)
    return APIResponse.from_data(
        SupportTicketOut.model_validate(result, from_attributes=True)
    )


@router.post("")
async def create(
    data: AdminTicketCreate,
    principal: Annotated[Principal, scoped("support")],
    command: FromDishka[ISupportCreateCommand],
) -> APIResponse[SupportTicketOut, None]:
    """Create a ticket from an established customer record."""
    result = await command.create(
        data.customer_id,
        TicketCreate.model_validate(data.model_dump()),
        staff_id=principal.staff_id,
    )
    return APIResponse.from_data(
        SupportTicketOut.model_validate(result, from_attributes=True)
    )


@router.post("/{id:int}/messages")
async def reply(
    id: int,
    data: TicketReply,
    principal: Annotated[Principal, scoped("support", "update")],
    command: FromDishka[ISupportThreadCommand],
) -> APIResponse[SupportTicketOut, None]:
    """Append a staff reply within current support policy."""
    result = await command.reply(id, data, staff_id=principal.staff_id)
    return APIResponse.from_data(
        SupportTicketOut.model_validate(result, from_attributes=True)
    )


@router.put("/{id:int}/state")
async def state(
    id: int,
    data: TicketStateWrite,
    principal: Annotated[Principal, scoped("support", "update")],
    command: FromDishka[ISupportThreadCommand],
) -> APIResponse[SupportTicketOut, None]:
    """Change ticket state and record the operator's reason."""
    result = await command.state(id, data, staff_id=principal.staff_id)
    return APIResponse.from_data(
        SupportTicketOut.model_validate(result, from_attributes=True)
    )


@router.get("/{id:int}/messages", dependencies=[scoped("support")])
async def messages(
    id: int,
    data: Annotated[ThreadSearch, Query()],
    tickets: FromDishka[ISupportTicketQuery],
    service: FromDishka[ISupportMessageQuery],
) -> APIResponse[AdminSupportMessageOut, BaseMeta]:
    """Page through immutable messages and author identities."""
    await tickets.get(id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[AdminSupportMessageOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}/history", dependencies=[scoped("support")])
async def history(
    id: int,
    data: Annotated[ThreadSearch, Query()],
    tickets: FromDishka[ISupportTicketQuery],
    service: FromDishka[ISupportHistoryQuery],
) -> APIResponse[AdminSupportHistoryOut, BaseMeta]:
    """Page through immutable state changes and author identities."""
    await tickets.get(id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[AdminSupportHistoryOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
