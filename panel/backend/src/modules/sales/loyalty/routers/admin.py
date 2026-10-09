from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.sales.loyalty.domain.dtos import (
    CustomerTierWrite,
    LoyaltyPolicyWrite,
    LoyaltySearch,
)
from src.modules.sales.loyalty.domain.models import CustomerTierModel
from src.modules.sales.loyalty.domain.results import (
    CustomerPriceQuote,
    CustomerTierRead,
    LoyaltyPolicyRead,
)
from src.modules.sales.loyalty.interfaces import (
    ICustomerLoyaltyQuery,
    ICustomerTierService,
    ILoyaltyInitializeCommand,
    ILoyaltyPolicyService,
)

router = APIRouter(
    prefix="/v1/admin/loyalty",
    tags=["Customer loyalty"],
    route_class=DishkaRoute,
    dependencies=[scoped("catalog")],
)


@router.get("/tiers")
async def tiers(
    data: Annotated[LoyaltySearch, Query()],
    service: FromDishka[ICustomerTierService],
) -> APIResponse[CustomerTierModel, BaseMeta]:
    """Page persistent customer tiers."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/tiers")
async def create(
    data: CustomerTierWrite, service: FromDishka[ICustomerTierService]
) -> APIResponse[CustomerTierModel, None]:
    """Create an editable purchase-volume tier."""
    result = await service.create(data)
    return APIResponse.from_data(result)


@router.put("/tiers/{id:int}")
async def update(
    id: int, data: CustomerTierWrite, service: FromDishka[ICustomerTierService]
) -> APIResponse[CustomerTierModel, None]:
    """Update the selected tier with revision protection."""
    result = await service.update(id, data)
    return APIResponse.from_data(result)


@router.get("/policy")
async def policy(
    service: FromDishka[ILoyaltyPolicyService],
) -> APIResponse[LoyaltyPolicyRead, None]:
    """Read effective loyalty and discount rules."""
    result = await service.current()
    return APIResponse.from_data(result)


@router.put("/policy")
async def set_policy(
    data: LoyaltyPolicyWrite, service: FromDishka[ILoyaltyPolicyService]
) -> APIResponse[LoyaltyPolicyRead, None]:
    """Save rules without rewriting completed purchase prices."""
    result = await service.update(data)
    return APIResponse.from_data(result)


@router.post("/initialize")
async def initialize(
    command: FromDishka[ILoyaltyInitializeCommand],
) -> APIResponse[LoyaltyPolicyRead, None]:
    """Seed configured missing tiers and policy, preserving operator edits."""
    result = await command.initialize()
    return APIResponse.from_data(result)


@router.get("/customers/{customer_id:int}", dependencies=[scoped("customers")])
async def status(
    customer_id: int, query: FromDishka[ICustomerLoyaltyQuery]
) -> APIResponse[CustomerTierRead, None]:
    """Read the selected customer's current and next tier."""
    result = await query.status(customer_id)
    return APIResponse.from_data(result)


@router.get(
    "/customers/{customer_id:int}/plans/{plan_id:int}/quote",
    dependencies=[scoped("customers")],
)
async def quote(
    customer_id: int, plan_id: int, query: FromDishka[ICustomerLoyaltyQuery]
) -> APIResponse[CustomerPriceQuote, None]:
    """Quote a selected customer's purchase without charging."""
    result = await query.quote(customer_id, plan_id)
    return APIResponse.from_data(result)
