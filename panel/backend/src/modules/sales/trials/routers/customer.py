from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from papilio.api.responses.envelope import APIResponse

from src.modules.accounts.customer_auth.config.dependencies import (
    CurrentCustomer,
    WritableCustomer,
)
from src.modules.network.ip_limits.interfaces import IIpPolicyProjectionQuery
from src.modules.sales.subscriptions.routers.schemas import SubscriptionOut
from src.modules.sales.trials.domain.dtos import TrialClaim
from src.modules.sales.trials.domain.results import TrialAvailability
from src.modules.sales.trials.interfaces import ITrialCommand, ITrialQuery

router = APIRouter(
    prefix="/v1/customer/trials",
    tags=["Customer Trials"],
    route_class=DishkaRoute,
)


@router.get("/availability")
async def availability(
    principal: CurrentCustomer, query: FromDishka[ITrialQuery]
) -> APIResponse[TrialAvailability, None]:
    """Read eligibility and the current trial offer for this account."""
    result = await query.availability(principal.customer_id)
    return APIResponse.from_data(result)


@router.post("")
async def claim(
    data: TrialClaim,
    principal: WritableCustomer,
    command: FromDishka[ITrialCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, None]:
    """Claim a replay-safe free entitlement pending actual provisioning."""
    result = await command.claim(principal.customer_id, data)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(SubscriptionOut.from_model(result, ip_policy))
