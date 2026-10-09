from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.network.usage.domain.dtos import UsageSearch
from src.modules.network.usage.domain.results import UsageSummary
from src.modules.network.usage.interfaces import IUsageQuery
from src.modules.network.usage.routers.schemas import EventOut, GrantOut

router = APIRouter(
    prefix="/v1/admin/usage",
    tags=["Usage Accounting"],
    route_class=DishkaRoute,
    dependencies=[scoped("subscriptions")],
)


@router.get("/grants")
async def grants(
    data: Annotated[UsageSearch, Query()], query: FromDishka[IUsageQuery]
) -> APIResponse[GrantOut, BaseMeta]:
    """Page node budgets and their final counter status."""
    result = await query.grants(data)
    return APIResponse(
        success=True,
        data=[
            GrantOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/events")
async def events(
    data: Annotated[UsageSearch, Query()], query: FromDishka[IUsageQuery]
) -> APIResponse[EventOut, BaseMeta]:
    """Page accepted usage deltas by subscription, node and date."""
    result = await query.events(data)
    return APIResponse(
        success=True,
        data=[
            EventOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/summary")
async def summary(
    data: Annotated[UsageSearch, Query()], query: FromDishka[IUsageQuery]
) -> APIResponse[UsageSummary, None]:
    """Summarize accepted usage over the complete filtered range."""
    result = await query.summary(data)
    return APIResponse.from_data(result)
