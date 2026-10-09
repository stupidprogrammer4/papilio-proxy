from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.sales.catalog.domain.bundles import (
    PlanConfigurationRead,
    PlanConfigurationSearch,
)
from src.modules.sales.catalog.domain.dtos import PlanSearch
from src.modules.sales.catalog.interfaces import (
    IPlanConfigurationQuery,
    IPlanService,
)
from src.modules.sales.catalog.routers.schemas import PlanOut

router = APIRouter(prefix="/v1/plans", tags=["Plans"], route_class=DishkaRoute)


@router.get("")
async def plans(
    data: Annotated[PlanSearch, Query()],
    service: FromDishka[IPlanService],
) -> APIResponse[PlanOut, BaseMeta]:
    """Page the active public plan catalog."""
    public = data.model_copy(update={"active": True})
    result = await service.search(public)
    return APIResponse(
        success=True,
        data=[PlanOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}/configurations")
async def configurations(
    id: int,
    data: Annotated[PlanConfigurationSearch, Query()],
    query: FromDishka[IPlanConfigurationQuery],
) -> APIResponse[PlanConfigurationRead, BaseMeta]:
    """Read the selected plan's configuration bundle without credentials."""
    result = await query.search(id, data, public=True)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
