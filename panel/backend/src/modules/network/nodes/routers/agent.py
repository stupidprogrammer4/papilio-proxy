from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header

from src.modules.network.nodes.domain.dtos import ProbeReceived
from src.modules.network.nodes.interfaces import IProbeCommand

router = APIRouter(
    prefix="/v1/nodes", tags=["Node Telemetry"], route_class=DishkaRoute
)


@router.post("/{code}/probes")
async def receive(
    code: str,
    data: ProbeReceived,
    command: FromDishka[IProbeCommand],
    x_papilio_node_key: str = Header(default=""),
) -> dict[str, bool]:
    """Record a signed endpoint probe without provisioning a proxy."""
    await command.receive(code, x_papilio_node_key, data)
    return {"accepted": True}
