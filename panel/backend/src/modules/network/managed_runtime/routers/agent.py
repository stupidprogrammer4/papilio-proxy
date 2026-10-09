from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Response
from papilio.api.responses.envelope import APIResponse

from src.modules.network.managed_runtime.domain.installations import (
    ManagedClosedStartupAcknowledgement,
    ManagedInstallationClaim,
    ManagedInstalledClosedOut,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedInstallationCommand,
)

router = APIRouter(
    prefix="/v1/nodes", tags=["Managed installation"], route_class=DishkaRoute
)


@router.post("/{code}/managed-installations/{id:int}/claim")
async def claim(
    code: str,
    id: int,
    response: Response,
    command: FromDishka[IManagedInstallationCommand],
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedInstallationClaim, None]:
    """Claim one issued installation; no traffic is admitted."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.claim(code, x_papilio_node_key, id)
    return APIResponse.from_data(result)


@router.post("/{code}/managed-installations/{id:int}/acknowledge")
async def acknowledge(
    code: str,
    id: int,
    data: ManagedClosedStartupAcknowledgement,
    response: Response,
    command: FromDishka[IManagedInstallationCommand],
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedInstalledClosedOut, None]:
    """Accept the original historical CLOSED startup receipt."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.acknowledge(code, x_papilio_node_key, id, data)
    return APIResponse.from_data(result)
