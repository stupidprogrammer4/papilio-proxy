from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.resellers.domain.dtos import (
    ResellerAccountCreate,
    ResellerAccountWrite,
    ResellerPasswordWrite,
    ResellerSearch,
)
from src.modules.accounts.resellers.domain.results import ResellerAccountActor
from src.modules.accounts.resellers.interfaces import (
    IResellerAccountCommand,
    IResellerAccountHistoryQuery,
    IResellerAccountQuery,
)
from src.modules.accounts.resellers.routers.schemas import (
    ResellerAccountChangeOut,
    ResellerAccountOut,
)
from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal

router = APIRouter(
    prefix="/v1/admin/resellers/{reseller_id:int}/accounts",
    tags=["Admin Reseller Accounts"],
    route_class=DishkaRoute,
)


@router.get("", dependencies=[scoped("resellers", "read")])
async def page(
    reseller_id: int,
    data: Annotated[ResellerSearch, Query()],
    query: FromDishka[IResellerAccountQuery],
) -> APIResponse[ResellerAccountOut, BaseMeta]:
    """Search accounts within this selected reseller."""
    result = await query.search(reseller_id, data)
    return APIResponse(
        success=True,
        data=[ResellerAccountOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page,
                result.per_page,
                result.total_items,
            )
        ),
    )


@router.get("/{id:int}", dependencies=[scoped("resellers", "read")])
async def detail(
    reseller_id: int,
    id: int,
    query: FromDishka[IResellerAccountQuery],
) -> APIResponse[ResellerAccountOut, None]:
    """Read an account only under its actual owning reseller."""
    result = await query.get(reseller_id, id)
    return APIResponse.from_data(ResellerAccountOut.from_model(result))


@router.post("")
async def create(
    reseller_id: int,
    data: ResellerAccountCreate,
    actor: Annotated[Principal, scoped("resellers", "manage")],
    command: FromDishka[IResellerAccountCommand],
) -> APIResponse[ResellerAccountOut, None]:
    """Add a scoped member to the known reseller."""
    result = await command.create(
        reseller_id, data, ResellerAccountActor(staff_id=actor.staff_id)
    )
    return APIResponse.from_data(ResellerAccountOut.from_model(result))


@router.put("/{id:int}")
async def update(
    reseller_id: int,
    id: int,
    data: ResellerAccountWrite,
    actor: Annotated[Principal, scoped("resellers", "manage")],
    command: FromDishka[IResellerAccountCommand],
) -> APIResponse[ResellerAccountOut, None]:
    """Revise this member's access with an explicit expected revision."""
    result = await command.update(
        reseller_id, id, data, ResellerAccountActor(staff_id=actor.staff_id)
    )
    return APIResponse.from_data(ResellerAccountOut.from_model(result))


@router.put("/{id:int}/password")
async def password(
    reseller_id: int,
    id: int,
    data: ResellerPasswordWrite,
    actor: Annotated[Principal, scoped("resellers", "manage")],
    command: FromDishka[IResellerAccountCommand],
) -> APIResponse[ResellerAccountOut, None]:
    """Reset credentials and invalidate all older account sessions."""
    result = await command.reset_password(
        reseller_id, id, data, ResellerAccountActor(staff_id=actor.staff_id)
    )
    return APIResponse.from_data(ResellerAccountOut.from_model(result))


@router.get("/{id:int}/history", dependencies=[scoped("resellers", "read")])
async def history(
    reseller_id: int,
    id: int,
    data: Annotated[ResellerSearch, Query()],
    query: FromDishka[IResellerAccountHistoryQuery],
) -> APIResponse[ResellerAccountChangeOut, BaseMeta]:
    """Read this member's scoped access and credential-change history."""
    result = await query.search(reseller_id, id, data)
    return APIResponse(
        success=True,
        data=[
            ResellerAccountChangeOut.from_model(row) for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page,
                result.per_page,
                result.total_items,
            )
        ),
    )
