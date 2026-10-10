from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Path, Response
from papilio.api.responses.envelope import APIResponse

from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalOut,
    ManagedWindowFinalSubmission,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedClosedStartupAcknowledgement,
    ManagedInstallationClaim,
    ManagedInstalledClosedOut,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowCreate,
    ManagedInitialWindowOut,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedFinalityCommand,
    IManagedInitialWindowCommand,
    IManagedInstallationCommand,
)

router = APIRouter(
    prefix="/v1/nodes", tags=["Managed installation"], route_class=DishkaRoute
)


@router.post("/{code}/managed-windows/{window_id}/finalize")
async def finalize(
    code: str,
    data: ManagedWindowFinalSubmission,
    response: Response,
    command: FromDishka[IManagedFinalityCommand],
    window_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedWindowFinalOut, None]:
    """Settle one original frozen window; replay retains its acceptance."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.finalize(code, x_papilio_node_key, window_id, data)
    return APIResponse.from_data(result)


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


@router.post("/{code}/managed-installations/{id:int}/windows")
async def initial_window(
    code: str,
    id: int,
    data: ManagedInitialWindowCreate,
    response: Response,
    command: FromDishka[IManagedInitialWindowCommand],
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedInitialWindowOut, None]:
    """Reserve one initial window; paid activation remains unavailable."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.issue(code, x_papilio_node_key, id, data)
    return APIResponse.from_data(result)
