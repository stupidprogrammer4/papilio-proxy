from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Response
from papilio.api.responses.envelope import APIResponse

from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityReceived,
)
from src.modules.network.node_capabilities.domain.results import (
    NodeCapabilityReceipt,
)
from src.modules.network.node_capabilities.interfaces import (
    INodeCapabilityCommand,
)

router = APIRouter(
    prefix="/v1/nodes",
    tags=["Node capability observations"],
    route_class=DishkaRoute,
)


@router.post("/{code}/capability-observations")
async def receive(
    code: str,
    data: NodeCapabilityReceived,
    command: FromDishka[INodeCapabilityCommand],
    response: Response,
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[NodeCapabilityReceipt, None]:
    """Record authenticated metadata without core authorization."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.receive(code, x_papilio_node_key, data)
    return APIResponse.from_data(result)
