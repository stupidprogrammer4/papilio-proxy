from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilitySearch,
)
from src.modules.network.node_capabilities.domain.results import (
    NodeCapabilityLatest,
    NodeCapabilityObservation,
)
from src.modules.network.node_capabilities.interfaces import (
    INodeCapabilityQuery,
)

router = APIRouter(
    prefix="/v1/admin/network/nodes",
    tags=["Node capability observations"],
    route_class=DishkaRoute,
    dependencies=[scoped("network")],
)


@router.get("/{id:int}/capabilities/latest")
async def latest(
    id: int, query: FromDishka[INodeCapabilityQuery], response: Response
) -> APIResponse[NodeCapabilityLatest, None]:
    """Read authenticated self-report freshness."""
    response.headers["Cache-Control"] = "no-store"
    result = await query.latest(id)
    return APIResponse.from_data(result)


@router.get("/{id:int}/capabilities/history")
async def history(
    id: int,
    data: Annotated[NodeCapabilitySearch, Query()],
    query: FromDishka[INodeCapabilityQuery],
    response: Response,
) -> APIResponse[NodeCapabilityObservation, BaseMeta]:
    """Browse immutable self-report receipts in their actual node context."""
    response.headers["Cache-Control"] = "no-store"
    result = await query.history(id, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
