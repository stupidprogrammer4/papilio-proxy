from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from papilio.api.responses.envelope import APIResponse

from src.modules.accounts.customer_auth.config.dependencies import (
    CurrentCustomer,
)
from src.modules.sales.loyalty.domain.results import (
    CustomerPriceQuote,
    CustomerTierRead,
)
from src.modules.sales.loyalty.interfaces import ICustomerLoyaltyQuery

router = APIRouter(
    prefix="/v1/customer", tags=["Customer loyalty"], route_class=DishkaRoute
)


@router.get("/loyalty")
async def status(
    principal: CurrentCustomer, query: FromDishka[ICustomerLoyaltyQuery]
) -> APIResponse[CustomerTierRead, None]:
    """Read purchase-volume progress for the authenticated customer."""
    result = await query.status(principal.customer_id)
    return APIResponse.from_data(result)


@router.get("/plans/{plan_id:int}/quote")
async def quote(
    plan_id: int,
    principal: CurrentCustomer,
    query: FromDishka[ICustomerLoyaltyQuery],
) -> APIResponse[CustomerPriceQuote, None]:
    """Read the authenticated customer's current purchase price."""
    result = await query.quote(principal.customer_id, plan_id)
    return APIResponse.from_data(result)
