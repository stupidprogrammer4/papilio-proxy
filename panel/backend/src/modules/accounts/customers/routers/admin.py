from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.customers.domain.configurations import (
    CustomerConfigurationRead,
    CustomerConfigurationSearch,
)
from src.modules.accounts.customers.domain.dtos import (
    CustomerAccessSearch,
    CustomerAccessState,
    CustomerAccessWrite,
    CustomerCreate,
    CustomerProfileWrite,
    CustomerSearch,
)
from src.modules.accounts.customers.domain.results import (
    StaffCustomerAccessActor,
)
from src.modules.accounts.customers.interfaces import (
    ICustomerAccessCommand,
    ICustomerAccessQuery,
    ICustomerConfigurationQuery,
    ICustomerService,
)
from src.modules.accounts.customers.routers.schemas import (
    CustomerAccessChangeOut,
    CustomerOut,
)
from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal

router = APIRouter(
    prefix="/v1/admin/customers",
    tags=["Admin Customers"],
    route_class=DishkaRoute,
    dependencies=[scoped("customers")],
)


@router.get("")
async def page(
    data: Annotated[CustomerSearch, Query()],
    service: FromDishka[ICustomerService],
) -> APIResponse[CustomerOut, BaseMeta]:
    """Search customers with complete pagination."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[CustomerOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("")
async def create(
    data: CustomerCreate, service: FromDishka[ICustomerService]
) -> APIResponse[CustomerOut, None]:
    """Create a customer profile."""
    result = await service.create(data)
    return APIResponse.from_data(CustomerOut.from_model(result))


@router.get("/creation-policy")
async def creation_policy(
    service: FromDishka[ICustomerService],
) -> APIResponse[CustomerAccessState, None]:
    """Read application-owned defaults for new customer accounts."""
    result = await service.creation_access()
    return APIResponse.from_data(result)


@router.get("/{id:int}")
async def detail(
    id: int, service: FromDishka[ICustomerService]
) -> APIResponse[CustomerOut, None]:
    """Read a selected customer without losing its identity."""
    result = await service.get(id)
    return APIResponse.from_data(CustomerOut.from_model(result))


@router.put("/{id:int}/profile")
async def update_profile(
    id: int, data: CustomerProfileWrite, service: FromDishka[ICustomerService]
) -> APIResponse[CustomerOut, None]:
    """Edit the selected profile without replacing its Telegram identity."""
    result = await service.update_profile(id, data)
    return APIResponse.from_data(CustomerOut.from_model(result))


@router.put("/{id:int}/access")
async def access(
    id: int,
    data: CustomerAccessWrite,
    principal: Annotated[Principal, scoped("customers")],
    command: FromDishka[ICustomerAccessCommand],
) -> APIResponse[CustomerOut, None]:
    """Update selected account, service and renewal access independently."""
    result = await command.update(
        id, data, StaffCustomerAccessActor(principal.staff_id)
    )
    return APIResponse.from_data(CustomerOut.from_model(result))


@router.get("/{id:int}/access-history")
async def access_history(
    id: int,
    data: Annotated[CustomerAccessSearch, Query()],
    query: FromDishka[ICustomerAccessQuery],
) -> APIResponse[CustomerAccessChangeOut, BaseMeta]:
    """Read complete paged access-change history."""
    result = await query.search(id, data)
    return APIResponse(
        success=True,
        data=[
            CustomerAccessChangeOut.from_model(item) for item in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get(
    "/{id:int}/configurations",
    dependencies=[scoped("network", "read"), scoped("subscriptions", "read")],
)
async def configurations(
    id: int,
    data: Annotated[CustomerConfigurationSearch, Query()],
    query: FromDishka[ICustomerConfigurationQuery],
) -> APIResponse[CustomerConfigurationRead, BaseMeta]:
    """Read the customer's assigned configurations and purchase context."""
    result = await query.search(id, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
