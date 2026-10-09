from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.customer_auth.config.dependencies import (
    CurrentCustomer,
    WritableCustomer,
)
from src.modules.support.domain.dtos import (
    CustomerTicketSearch,
    ThreadSearch,
    TicketCreate,
    TicketReply,
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
    SupportHistoryOut,
    SupportMessageOut,
    SupportPolicyOut,
    SupportTicketOut,
)

router = APIRouter(
    prefix="/v1/customer/support",
    tags=["Customer Support"],
    route_class=DishkaRoute,
)


@router.get("/policy")
async def policy(
    _: CurrentCustomer, service: FromDishka[ISupportPolicyQuery]
) -> APIResponse[SupportPolicyOut, None]:
    """Read current support permissions and capacities."""
    result = await service.current()
    return APIResponse.from_data(
        SupportPolicyOut(
            **result.values.model_dump(), capacity_valid=result.capacity_valid
        )
    )


@router.get("")
async def search(
    data: Annotated[CustomerTicketSearch, Query()],
    principal: CurrentCustomer,
    service: FromDishka[ISupportTicketQuery],
) -> APIResponse[SupportTicketOut, BaseMeta]:
    """Search tickets belonging to this customer."""
    result = await service.search_customer(principal.customer_id, data)
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


@router.get("/{id:int}")
async def detail(
    id: int,
    principal: CurrentCustomer,
    service: FromDishka[ISupportTicketQuery],
) -> APIResponse[SupportTicketOut, None]:
    """Read this account's selected ticket."""
    result = await service.get_for_customer(id, principal.customer_id)
    return APIResponse.from_data(
        SupportTicketOut.model_validate(result, from_attributes=True)
    )


@router.post("")
async def create(
    data: TicketCreate,
    principal: WritableCustomer,
    command: FromDishka[ISupportCreateCommand],
) -> APIResponse[SupportTicketOut, None]:
    """Create a private ticket with an optional owned record context."""
    result = await command.create(principal.customer_id, data)
    return APIResponse.from_data(
        SupportTicketOut.model_validate(result, from_attributes=True)
    )


@router.post("/{id:int}/messages")
async def reply(
    id: int,
    data: TicketReply,
    principal: WritableCustomer,
    command: FromDishka[ISupportThreadCommand],
) -> APIResponse[SupportTicketOut, None]:
    """Append one customer message with replay protection."""
    result = await command.reply(id, data, customer_id=principal.customer_id)
    return APIResponse.from_data(
        SupportTicketOut.model_validate(result, from_attributes=True)
    )


@router.put("/{id:int}/state")
async def state(
    id: int,
    data: TicketStateWrite,
    principal: WritableCustomer,
    command: FromDishka[ISupportThreadCommand],
) -> APIResponse[SupportTicketOut, None]:
    """Close or reopen according to current support policy."""
    result = await command.state(id, data, customer_id=principal.customer_id)
    return APIResponse.from_data(
        SupportTicketOut.model_validate(result, from_attributes=True)
    )


@router.get("/{id:int}/messages")
async def messages(
    id: int,
    data: Annotated[ThreadSearch, Query()],
    principal: CurrentCustomer,
    tickets: FromDishka[ISupportTicketQuery],
    service: FromDishka[ISupportMessageQuery],
) -> APIResponse[SupportMessageOut, BaseMeta]:
    """Page through this account's immutable messages."""
    await tickets.get_for_customer(id, principal.customer_id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[SupportMessageOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}/history")
async def history(
    id: int,
    data: Annotated[ThreadSearch, Query()],
    principal: CurrentCustomer,
    tickets: FromDishka[ISupportTicketQuery],
    service: FromDishka[ISupportHistoryQuery],
) -> APIResponse[SupportHistoryOut, BaseMeta]:
    """Page through this account's ticket state history."""
    await tickets.get_for_customer(id, principal.customer_id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[SupportHistoryOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
