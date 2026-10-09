from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.customers.domain.dtos import (
    CustomerAccessSearch,
    CustomerAccessWrite,
    CustomerCreate,
    CustomerProfileWrite,
    CustomerSearch,
)
from src.modules.accounts.customers.routers.schemas import (
    CustomerAccessChangeOut,
    CustomerOut,
)
from src.modules.accounts.resellers.config.dependencies import (
    CurrentReseller,
    scoped,
)
from src.modules.accounts.resellers.domain.dtos import (
    RESELLER_AREAS,
    RESELLER_LEVELS,
)
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.accounts.resellers.interfaces import (
    IResellerCustomerCommand,
    IResellerCustomerQuery,
    IResellerRegistryQuery,
)
from src.modules.accounts.resellers.routers.schemas import (
    ResellerOut,
    ResellerScopeCatalog,
)

router = APIRouter(
    prefix="/v1/reseller", tags=["Reseller Customers"], route_class=DishkaRoute
)


@router.get("/profile")
async def profile(
    principal: CurrentReseller,
    query: FromDishka[IResellerRegistryQuery],
) -> APIResponse[ResellerOut, None]:
    """Read the current organization's effective policy and state."""
    result = await query.get(principal.reseller_id)
    return APIResponse.from_data(ResellerOut.from_model(result))


@router.get("/scope-catalog")
async def scope_catalog(
    _: CurrentReseller,
) -> APIResponse[ResellerScopeCatalog, None]:
    """Read supported capabilities for scoped team delegation."""
    return APIResponse.from_data(
        ResellerScopeCatalog(
            areas=list(RESELLER_AREAS), levels=list(RESELLER_LEVELS)
        )
    )


@router.get("/customers")
async def page(
    data: Annotated[CustomerSearch, Query()],
    principal: Annotated[ResellerPrincipal, scoped("customers", "read")],
    query: FromDishka[IResellerCustomerQuery],
) -> APIResponse[CustomerOut, BaseMeta]:
    """Search customers owned by this authenticated reseller."""
    result = await query.search(principal.reseller_id, data)
    return APIResponse(
        success=True,
        data=[CustomerOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page,
                result.per_page,
                result.total_items,
            )
        ),
    )


@router.post("/customers")
async def create(
    data: CustomerCreate,
    principal: Annotated[ResellerPrincipal, scoped("customers", "create")],
    command: FromDishka[IResellerCustomerCommand],
) -> APIResponse[CustomerOut, None]:
    """Create a customer and its ownership atomically under current policy."""
    result = await command.create(principal, data)
    return APIResponse.from_data(CustomerOut.from_model(result))


@router.get("/customers/{id:int}")
async def detail(
    id: int,
    principal: Annotated[ResellerPrincipal, scoped("customers", "read")],
    query: FromDishka[IResellerCustomerQuery],
) -> APIResponse[CustomerOut, None]:
    """Read a customer only within this reseller's ownership."""
    result = await query.get(principal.reseller_id, id)
    return APIResponse.from_data(CustomerOut.from_model(result))


@router.patch("/customers/{id:int}")
async def update(
    id: int,
    data: CustomerProfileWrite,
    principal: Annotated[ResellerPrincipal, scoped("customers", "update")],
    command: FromDishka[IResellerCustomerCommand],
) -> APIResponse[CustomerOut, None]:
    """Edit the selected owned customer's display name."""
    result = await command.update_profile(principal, id, data)
    return APIResponse.from_data(CustomerOut.from_model(result))


@router.put("/customers/{id:int}/access")
async def access(
    id: int,
    data: CustomerAccessWrite,
    principal: Annotated[ResellerPrincipal, scoped("customers", "update")],
    command: FromDishka[IResellerCustomerCommand],
) -> APIResponse[CustomerOut, None]:
    """Change owned customer access under the current organization policy."""
    result = await command.update_access(principal, id, data)
    return APIResponse.from_data(CustomerOut.from_model(result))


@router.get("/customers/{id:int}/access-history")
async def access_history(
    id: int,
    data: Annotated[CustomerAccessSearch, Query()],
    principal: Annotated[ResellerPrincipal, scoped("customers", "read")],
    query: FromDishka[IResellerCustomerQuery],
) -> APIResponse[CustomerAccessChangeOut, BaseMeta]:
    """Read the selected owned customer's complete access history."""
    result = await query.access_history(principal.reseller_id, id, data)
    return APIResponse(
        success=True,
        data=[CustomerAccessChangeOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
