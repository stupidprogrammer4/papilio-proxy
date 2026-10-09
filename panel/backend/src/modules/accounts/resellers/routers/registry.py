from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.resellers.domain.dtos import (
    RESELLER_AREAS,
    RESELLER_LEVELS,
    ResellerCreate,
    ResellerDefaults,
    ResellerSearch,
    ResellerWrite,
)
from src.modules.accounts.resellers.interfaces import (
    IResellerRegistryCommand,
    IResellerRegistryHistoryQuery,
    IResellerRegistryQuery,
)
from src.modules.accounts.resellers.routers.schemas import (
    CreatedResellerOut,
    ResellerAccountOut,
    ResellerChangeOut,
    ResellerOut,
    ResellerScopeCatalog,
)
from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal

router = APIRouter(
    prefix="/v1/admin/resellers",
    tags=["Admin Resellers"],
    route_class=DishkaRoute,
)


@router.get("", dependencies=[scoped("resellers", "read")])
async def page(
    data: Annotated[ResellerSearch, Query()],
    query: FromDishka[IResellerRegistryQuery],
) -> APIResponse[ResellerOut, BaseMeta]:
    """Search all reseller organizations with full pagination."""
    result = await query.search(data)
    return APIResponse(
        success=True,
        data=[ResellerOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page,
                result.per_page,
                result.total_items,
            )
        ),
    )


@router.get("/defaults", dependencies=[scoped("resellers", "read")])
async def defaults(
    query: FromDishka[IResellerRegistryQuery],
) -> APIResponse[ResellerDefaults, None]:
    """Read effective defaults for new reseller organizations."""
    result = await query.defaults()
    return APIResponse.from_data(result)


@router.get("/scope-catalog", dependencies=[scoped("resellers", "read")])
async def scope_catalog() -> APIResponse[ResellerScopeCatalog, None]:
    """Read supported capabilities within the reseller realm."""
    return APIResponse.from_data(
        ResellerScopeCatalog(
            areas=list(RESELLER_AREAS), levels=list(RESELLER_LEVELS)
        )
    )


@router.post("")
async def create(
    data: ResellerCreate,
    actor: Annotated[Principal, scoped("resellers", "create")],
    command: FromDishka[IResellerRegistryCommand],
) -> APIResponse[CreatedResellerOut, None]:
    """Register an organization, its wallet account and initial team member."""
    result = await command.create(data, actor.staff_id)
    return APIResponse.from_data(
        CreatedResellerOut(
            reseller=ResellerOut.from_model(result.reseller),
            owner=ResellerAccountOut.from_model(result.owner),
        )
    )


@router.get("/{id:int}", dependencies=[scoped("resellers", "read")])
async def detail(
    id: int,
    query: FromDishka[IResellerRegistryQuery],
) -> APIResponse[ResellerOut, None]:
    """Read this organization's policy and access state."""
    result = await query.get(id)
    return APIResponse.from_data(ResellerOut.from_model(result))


@router.put("/{id:int}")
async def update(
    id: int,
    data: ResellerWrite,
    actor: Annotated[Principal, scoped("resellers", "update")],
    command: FromDishka[IResellerRegistryCommand],
) -> APIResponse[ResellerOut, None]:
    """Revise organization policies with immutable actor history."""
    result = await command.update(id, data, actor.staff_id)
    return APIResponse.from_data(ResellerOut.from_model(result))


@router.get("/{id:int}/history", dependencies=[scoped("resellers", "read")])
async def history(
    id: int,
    data: Annotated[ResellerSearch, Query()],
    query: FromDishka[IResellerRegistryHistoryQuery],
) -> APIResponse[ResellerChangeOut, BaseMeta]:
    """Read the complete paged policy history for this organization."""
    result = await query.search(id, data)
    return APIResponse(
        success=True,
        data=[ResellerChangeOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page,
                result.per_page,
                result.total_items,
            )
        ),
    )
