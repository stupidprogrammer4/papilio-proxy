from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.billing.destinations.domain.dtos import (
    DestinationSearch,
    DestinationWrite,
)
from src.modules.billing.destinations.domain.results import DestinationDetails
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)

router = APIRouter(
    prefix="/v1/admin/payments/destinations",
    tags=["Payment Destinations"],
    route_class=DishkaRoute,
    dependencies=[scoped("payments")],
)


@router.get("")
async def page(
    data: Annotated[DestinationSearch, Query()],
    service: FromDishka[IPaymentDestinationService],
) -> APIResponse[DestinationDetails, BaseMeta]:
    """Search configured payment destinations."""
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


@router.get("/{id:int}")
async def detail(
    id: int, service: FromDishka[IPaymentDestinationService]
) -> APIResponse[DestinationDetails, None]:
    """Read one destination for editing or a known selection."""
    result = await service.get(id)
    return APIResponse.from_data(result)


@router.post("")
async def create(
    data: DestinationWrite, service: FromDishka[IPaymentDestinationService]
) -> APIResponse[DestinationDetails, None]:
    """Create an encrypted bank destination."""
    result = await service.create(data)
    return APIResponse.from_data(result)


@router.put("/{id:int}")
async def update(
    id: int,
    data: DestinationWrite,
    service: FromDishka[IPaymentDestinationService],
) -> APIResponse[DestinationDetails, None]:
    """Edit or disable the selected destination."""
    result = await service.update(id, data)
    return APIResponse.from_data(result)
