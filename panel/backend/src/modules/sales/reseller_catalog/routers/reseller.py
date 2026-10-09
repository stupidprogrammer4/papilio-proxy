from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.resellers.config.dependencies import scoped
from src.modules.accounts.resellers.domain.dtos import ResellerSearch
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.sales.reseller_catalog.interfaces import IResellerPlanQuery
from src.modules.sales.reseller_catalog.routers.schemas import AgreementOut

router = APIRouter(
    prefix="/v1/reseller/plans",
    tags=["Reseller Plans"],
    route_class=DishkaRoute,
)


@router.get("")
async def page(
    data: Annotated[ResellerSearch, Query()],
    principal: Annotated[ResellerPrincipal, scoped("catalog", "read")],
    query: FromDishka[IResellerPlanQuery],
) -> APIResponse[AgreementOut, BaseMeta]:
    """Search assigned, enabled plans that remain active."""
    result = await query.offered(principal.reseller_id, data)
    return APIResponse(
        success=True,
        data=[AgreementOut.from_quote(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
