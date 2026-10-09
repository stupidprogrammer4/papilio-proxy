from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Response
from papilio.api.responses.envelope import APIResponse

from src.modules.network.usage.domain.dtos import UsageAllocation, UsageReport
from src.modules.network.usage.interfaces import IUsageCommand
from src.modules.network.usage.routers.schemas import EventOut, GrantOut

router = APIRouter(
    prefix="/v1/nodes/{code}/usage",
    tags=["Node Usage"],
    route_class=DishkaRoute,
)


@router.post("/grants")
async def allocate(
    code: str,
    data: UsageAllocation,
    command: FromDishka[IUsageCommand],
    response: Response,
    x_papilio_node_key: str = Header(),
) -> APIResponse[GrantOut, None]:
    """Allocate a node-owned counter epoch and optional shared byte budget."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.allocate(code, x_papilio_node_key, data)
    return APIResponse.from_data(
        GrantOut.model_validate(result, from_attributes=True)
    )


@router.post("/grants/{id:int}/reports")
async def report(
    code: str,
    id: int,
    data: UsageReport,
    command: FromDishka[IUsageCommand],
    response: Response,
    x_papilio_node_key: str = Header(),
) -> APIResponse[EventOut, None]:
    """Submit counters; final confirms traffic stopped for this grant."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.report(code, x_papilio_node_key, id, data)
    return APIResponse.from_data(
        EventOut.model_validate(result, from_attributes=True)
    )
