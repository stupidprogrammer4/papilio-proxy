from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.resellers.domain.dtos import ResellerSearch
from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal
from src.modules.sales.reseller_catalog.domain.dtos import (
    AgreementCreate,
    AgreementWrite,
)
from src.modules.sales.reseller_catalog.interfaces import (
    IResellerPlanCommand,
    IResellerPlanHistoryQuery,
    IResellerPlanQuery,
)
from src.modules.sales.reseller_catalog.routers.schemas import (
    AgreementChangeOut,
    AgreementOut,
)

router = APIRouter(
    prefix="/v1/admin/resellers/{reseller_id:int}/plans",
    tags=["Admin Reseller Plans"],
    route_class=DishkaRoute,
)


@router.get("", dependencies=[scoped("resellers", "read")])
async def page(
    reseller_id: int,
    data: Annotated[ResellerSearch, Query()],
    query: FromDishka[IResellerPlanQuery],
) -> APIResponse[AgreementOut, BaseMeta]:
    """Search this organization's complete plan agreements."""
    result = await query.search(reseller_id, data)
    return APIResponse(
        success=True,
        data=[AgreementOut.from_quote(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("")
async def create(
    reseller_id: int,
    data: AgreementCreate,
    principal: Annotated[Principal, scoped("resellers", "manage")],
    command: FromDishka[IResellerPlanCommand],
    query: FromDishka[IResellerPlanQuery],
) -> APIResponse[AgreementOut, None]:
    """Assign one plan with explicit pricing and an immutable audit entry."""
    created = await command.create(reseller_id, data, principal.staff_id)
    result = await query.get(reseller_id, created.id)
    return APIResponse.from_data(AgreementOut.from_quote(result))


@router.get("/{id:int}", dependencies=[scoped("resellers", "read")])
async def detail(
    reseller_id: int,
    id: int,
    query: FromDishka[IResellerPlanQuery],
) -> APIResponse[AgreementOut, None]:
    """Read the current agreement and its calculated rial quote."""
    result = await query.get(reseller_id, id)
    return APIResponse.from_data(AgreementOut.from_quote(result))


@router.put("/{id:int}")
async def update(
    reseller_id: int,
    id: int,
    data: AgreementWrite,
    principal: Annotated[Principal, scoped("resellers", "manage")],
    command: FromDishka[IResellerPlanCommand],
    query: FromDishka[IResellerPlanQuery],
) -> APIResponse[AgreementOut, None]:
    """Revise pricing or availability if the loaded revision is current."""
    await command.update(reseller_id, id, data, principal.staff_id)
    result = await query.get(reseller_id, id)
    return APIResponse.from_data(AgreementOut.from_quote(result))


@router.get("/{id:int}/history", dependencies=[scoped("resellers", "read")])
async def history(
    reseller_id: int,
    id: int,
    data: Annotated[ResellerSearch, Query()],
    query: FromDishka[IResellerPlanHistoryQuery],
) -> APIResponse[AgreementChangeOut, BaseMeta]:
    """Read every agreement revision within its original organization."""
    result = await query.search(reseller_id, id, data)
    return APIResponse(
        success=True,
        data=[AgreementChangeOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
