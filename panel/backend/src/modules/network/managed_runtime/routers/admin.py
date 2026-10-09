from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from papilio.api.responses.envelope import APIResponse

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationCreate,
    ManagedInstallationOut,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedInstallationCommand,
)

router = APIRouter(
    prefix="/v1/admin/network/cores",
    tags=["Managed installation"],
    route_class=DishkaRoute,
    dependencies=[scoped("network", "manage")],
)


@router.post("/{id:int}/managed-installations")
async def issue(
    id: int,
    data: ManagedInstallationCreate,
    command: FromDishka[IManagedInstallationCommand],
) -> APIResponse[ManagedInstallationOut, None]:
    """Issue a CLOSED expectation from an immutable native revision."""
    result = await command.issue(id, data)
    return APIResponse.from_data(
        ManagedInstallationOut.model_validate(result.model_dump())
    )
