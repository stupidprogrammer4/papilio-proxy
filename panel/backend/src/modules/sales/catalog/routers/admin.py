from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.sales.catalog.domain.bundles import (
    PlanConfigurationRead,
    PlanConfigurationSearch,
)
from src.modules.sales.catalog.domain.dtos import (
    PlanCreate,
    PlanSearch,
    PlanSetActive,
    PlanUpdate,
)
from src.modules.sales.catalog.domain.results import PlanPolicyDefaults
from src.modules.sales.catalog.interfaces import (
    IPlanConfigurationQuery,
    IPlanService,
)
from src.modules.sales.catalog.routers.schemas import PlanOut

router = APIRouter(
    prefix="/v1/admin/plans",
    tags=["Admin Plans"],
    route_class=DishkaRoute,
    dependencies=[scoped("catalog")],
)


@router.get("")
async def page(
    data: Annotated[PlanSearch, Query()],
    service: FromDishka[IPlanService],
) -> APIResponse[PlanOut, BaseMeta]:
    """Search every plan, including inactive entries."""
    result = await service.search(data)
    defaults = (await service.policy_defaults()).ip_limit
    return APIResponse(
        success=True,
        data=[PlanOut.from_model(item, defaults) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("")
async def create(
    data: PlanCreate, service: FromDishka[IPlanService]
) -> APIResponse[PlanOut, None]:
    """Create an inactive plan for owner review."""
    result = await service.create(data)
    defaults = (await service.policy_defaults()).ip_limit
    return APIResponse.from_data(PlanOut.from_model(result, defaults))


@router.get("/policy-defaults")
async def policy_defaults(
    service: FromDishka[IPlanService],
) -> APIResponse[PlanPolicyDefaults, None]:
    """Read effective defaults without broader settings access."""
    result = await service.policy_defaults()
    return APIResponse.from_data(result)


@router.get("/{id:int}")
async def detail(
    id: int, service: FromDishka[IPlanService]
) -> APIResponse[PlanOut, None]:
    """Read the selected plan, including inactive source records."""
    result = await service.get(id)
    defaults = (await service.policy_defaults()).ip_limit
    return APIResponse.from_data(PlanOut.from_model(result, defaults))


@router.patch("/{id:int}")
async def update(
    id: int, data: PlanUpdate, service: FromDishka[IPlanService]
) -> APIResponse[PlanOut, None]:
    """Change a plan without changing its code."""
    result = await service.update(id, data)
    defaults = (await service.policy_defaults()).ip_limit
    return APIResponse.from_data(PlanOut.from_model(result, defaults))


@router.patch("/{id:int}/active")
async def active(
    id: int, data: PlanSetActive, service: FromDishka[IPlanService]
) -> APIResponse[PlanOut, None]:
    """Enable or disable a plan."""
    result = await service.set_active(id, data)
    defaults = (await service.policy_defaults()).ip_limit
    return APIResponse.from_data(PlanOut.from_model(result, defaults))


@router.get("/{id:int}/configurations")
async def configurations(
    id: int,
    data: Annotated[PlanConfigurationSearch, Query()],
    query: FromDishka[IPlanConfigurationQuery],
) -> APIResponse[PlanConfigurationRead, BaseMeta]:
    """Read the selected plan's configuration bundle without credentials."""
    result = await query.search(id, data, public=False)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
