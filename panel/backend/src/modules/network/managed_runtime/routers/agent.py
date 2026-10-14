from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Path, Response
from papilio.api.responses.envelope import APIResponse

from src.modules.network.managed_runtime.domain.admissions import (
    ManagedAdmissionOut,
    ManagedAdmissionSubmission,
)
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalBatchCreate,
    ManagedWindowFinalBatchOut,
    ManagedWindowFinalOut,
    ManagedWindowFinalSubmission,
)
from src.modules.network.managed_runtime.domain.epoch_seals import (
    ManagedEpochSealOut,
    ManagedEpochSealSubmission,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedClosedStartupAcknowledgement,
    ManagedInstallationClaim,
    ManagedInstalledClosedOut,
)
from src.modules.network.managed_runtime.domain.revocations import (
    ManagedRevocationOut,
    ManagedRevocationSubmission,
)
from src.modules.network.managed_runtime.domain.rollovers import (
    ManagedEpochRolloverOut,
    ManagedEpochRolloverSubmission,
)
from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorWindowCreate,
    ManagedSuccessorWindowOut,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowBatchCreate,
    ManagedInitialWindowBatchOut,
    ManagedInitialWindowCreate,
    ManagedInitialWindowOut,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedAdmissionCommand,
    IManagedEpochSealCommand,
    IManagedFinalityBatchCommand,
    IManagedFinalityCommand,
    IManagedInitialWindowBatchCommand,
    IManagedInitialWindowCommand,
    IManagedInstallationCommand,
    IManagedRevocationCommand,
    IManagedSuccessorWindowCommand,
)

router = APIRouter(
    prefix="/v1/nodes", tags=["Managed installation"], route_class=DishkaRoute
)


@router.post("/{code}/managed-epochs/{process_epoch}/rollover")
async def rollover_epoch(
    code: str,
    process_epoch: str,
    data: ManagedEpochRolloverSubmission,
    response: Response,
    command: FromDishka[IManagedInstallationCommand],
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedEpochRolloverOut, None]:
    """Start one fresh CLOSED epoch after accepted finality."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.rollover(
        code, x_papilio_node_key, process_epoch, data
    )
    return APIResponse.from_data(result)


@router.post("/{code}/managed-epochs/{process_epoch}/seal")
async def seal_epoch(
    code: str,
    process_epoch: str,
    data: ManagedEpochSealSubmission,
    response: Response,
    command: FromDishka[IManagedEpochSealCommand],
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedEpochSealOut, None]:
    """Accept immutable historical finality for one completed process epoch."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.accept(
        code, x_papilio_node_key, process_epoch, data
    )
    return APIResponse.from_data(result)


@router.post("/{code}/managed-windows/{window_id}/successor")
async def successor(
    code: str,
    data: ManagedSuccessorWindowCreate,
    response: Response,
    command: FromDishka[IManagedSuccessorWindowCommand],
    window_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedSuccessorWindowOut, None]:
    """Continue from accepted original finality without a new payment."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.issue(code, x_papilio_node_key, window_id, data)
    return APIResponse.from_data(result)


@router.post("/{code}/managed-windows/{window_id}/revocation")
async def revocation(
    code: str,
    data: ManagedRevocationSubmission,
    response: Response,
    command: FromDishka[IManagedRevocationCommand],
    window_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedRevocationOut, None]:
    """Complete a bound revocation only after accepted original finality."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.acknowledge(
        code, x_papilio_node_key, window_id, data
    )
    return APIResponse.from_data(result)


@router.post("/{code}/managed-windows/{window_id}/admission")
async def admission(
    code: str,
    data: ManagedAdmissionSubmission,
    response: Response,
    command: FromDishka[IManagedAdmissionCommand],
    window_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedAdmissionOut, None]:
    """Accept original strict admission and advance the bound paid task."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.acknowledge(
        code, x_papilio_node_key, window_id, data
    )
    return APIResponse.from_data(result)


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


@router.post("/{code}/managed-windows/finalize/batch")
async def finalize_batch(
    code: str,
    data: ManagedWindowFinalBatchCreate,
    response: Response,
    command: FromDishka[IManagedFinalityBatchCommand],
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedWindowFinalBatchOut, None]:
    """Settle one original frozen snapshot for its explicit window set."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.finalize(code, x_papilio_node_key, data)
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
    """Reserve an initial window, optionally bound to a paid task lease."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.issue(code, x_papilio_node_key, id, data)
    return APIResponse.from_data(result)


@router.post("/{code}/managed-installations/{id:int}/windows/batch")
async def initial_windows_batch(
    code: str,
    id: int,
    data: ManagedInitialWindowBatchCreate,
    response: Response,
    command: FromDishka[IManagedInitialWindowBatchCommand],
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[ManagedInitialWindowBatchOut, None]:
    """Reserve initial windows for independent profiles atomically."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.issue(code, x_papilio_node_key, id, data)
    return APIResponse.from_data(result)
