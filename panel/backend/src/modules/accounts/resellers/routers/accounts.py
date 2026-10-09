from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.resellers.config.dependencies import scoped
from src.modules.accounts.resellers.domain.dtos import (
    RESELLER_AREAS,
    RESELLER_LEVELS,
    ResellerAccountCreate,
    ResellerAccountWrite,
    ResellerPasswordWrite,
    ResellerSearch,
)
from src.modules.accounts.resellers.domain.results import (
    ResellerAccountActor,
    ResellerPrincipal,
)
from src.modules.accounts.resellers.interfaces import (
    IResellerAccountCommand,
    IResellerAccountHistoryQuery,
    IResellerAccountQuery,
)
from src.modules.accounts.resellers.routers.schemas import (
    ResellerAccountChangeOut,
    ResellerAccountOut,
    ResellerScopeCatalog,
)

router = APIRouter(
    prefix="/v1/reseller/accounts",
    tags=["Reseller Team"],
    route_class=DishkaRoute,
)


@router.get("/scope-catalog", dependencies=[scoped("team", "read")])
async def scope_catalog() -> APIResponse[ResellerScopeCatalog, None]:
    """List supported reseller capabilities, separate from staff scopes."""
    return APIResponse.from_data(
        ResellerScopeCatalog(
            areas=list(RESELLER_AREAS),
            levels=list(RESELLER_LEVELS),
        )
    )


@router.get("")
async def page(
    data: Annotated[ResellerSearch, Query()],
    principal: Annotated[ResellerPrincipal, scoped("team", "read")],
    query: FromDishka[IResellerAccountQuery],
) -> APIResponse[ResellerAccountOut, BaseMeta]:
    """Search members of the authenticated reseller only."""
    result = await query.search(principal.reseller_id, data)
    return APIResponse(
        success=True,
        data=[ResellerAccountOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page,
                result.per_page,
                result.total_items,
            )
        ),
    )


@router.get("/{id:int}")
async def detail(
    id: int,
    principal: Annotated[ResellerPrincipal, scoped("team", "read")],
    query: FromDishka[IResellerAccountQuery],
) -> APIResponse[ResellerAccountOut, None]:
    """Read a selected member within this reseller."""
    result = await query.get(principal.reseller_id, id)
    return APIResponse.from_data(ResellerAccountOut.from_model(result))


@router.post("")
async def create(
    data: ResellerAccountCreate,
    principal: Annotated[ResellerPrincipal, scoped("team", "create")],
    command: FromDishka[IResellerAccountCommand],
) -> APIResponse[ResellerAccountOut, None]:
    """Delegate permitted capabilities to a new member of this reseller."""
    result = await command.create(
        principal.reseller_id, data, ResellerAccountActor(principal=principal)
    )
    return APIResponse.from_data(ResellerAccountOut.from_model(result))


@router.put("/{id:int}")
async def update(
    id: int,
    data: ResellerAccountWrite,
    principal: Annotated[ResellerPrincipal, scoped("team", "update")],
    command: FromDishka[IResellerAccountCommand],
) -> APIResponse[ResellerAccountOut, None]:
    """Revise an owned member while preserving delegation and owner rules."""
    result = await command.update(
        principal.reseller_id,
        id,
        data,
        ResellerAccountActor(principal=principal),
    )
    return APIResponse.from_data(ResellerAccountOut.from_model(result))


@router.put("/{id:int}/password")
async def password(
    id: int,
    data: ResellerPasswordWrite,
    principal: Annotated[ResellerPrincipal, scoped("team", "manage")],
    command: FromDishka[IResellerAccountCommand],
) -> APIResponse[ResellerAccountOut, None]:
    """Reset an owned member's password and revoke older sessions."""
    result = await command.reset_password(
        principal.reseller_id,
        id,
        data,
        ResellerAccountActor(principal=principal),
    )
    return APIResponse.from_data(ResellerAccountOut.from_model(result))


@router.get("/{id:int}/history")
async def history(
    id: int,
    data: Annotated[ResellerSearch, Query()],
    principal: Annotated[ResellerPrincipal, scoped("team", "read")],
    query: FromDishka[IResellerAccountHistoryQuery],
) -> APIResponse[ResellerAccountChangeOut, BaseMeta]:
    """Read the selected member's paged access history within this reseller."""
    result = await query.search(principal.reseller_id, id, data)
    return APIResponse(
        success=True,
        data=[
            ResellerAccountChangeOut.from_model(row) for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page,
                result.per_page,
                result.total_items,
            )
        ),
    )
