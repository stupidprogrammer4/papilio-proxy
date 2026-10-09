from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from papilio.api.responses.envelope import APIResponse

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal
from src.modules.network.ip_limits.interfaces import IIpPolicyProjectionQuery
from src.modules.sales.subscriptions.routers.schemas import SubscriptionOut
from src.modules.sales.trials.domain.dtos import TrialClaim
from src.modules.sales.trials.domain.results import TrialAvailability
from src.modules.sales.trials.interfaces import ITrialCommand, ITrialQuery

router = APIRouter(
    prefix="/v1/admin/customers",
    tags=["Admin Trials"],
    route_class=DishkaRoute,
)


@router.get("/{id:int}/trial-availability")
async def availability(
    id: int,
    _: Annotated[Principal, scoped("subscriptions")],
    query: FromDishka[ITrialQuery],
) -> APIResponse[TrialAvailability, None]:
    """Read the selected customer's trial eligibility."""
    result = await query.availability(id)
    return APIResponse.from_data(result)


@router.post("/{id:int}/trial")
async def claim(
    id: int,
    data: TrialClaim,
    _: Annotated[Principal, scoped("subscriptions")],
    command: FromDishka[ITrialCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, None]:
    """Apply the same trial rules for a selected customer."""
    result = await command.claim(id, data)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(SubscriptionOut.from_model(result, ip_policy))
