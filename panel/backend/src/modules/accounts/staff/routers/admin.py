from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.dtos import (
    STAFF_SCOPE_AREAS,
    STAFF_SCOPE_LEVELS,
    StaffAccessWrite,
    StaffCreate,
    StaffPasswordWrite,
    StaffSearch,
)
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.domain.results import Principal, StaffAccess
from src.modules.accounts.staff.interfaces import IStaffAdministration

router = APIRouter(
    prefix="/v1/admin/staff",
    tags=["Admin Staff"],
    route_class=DishkaRoute,
    dependencies=[scoped("staff")],
)


class StaffOut(BaseModel):
    id: int
    username: str
    is_active: bool

    @classmethod
    def from_model(cls, item: StaffModel) -> "StaffOut":
        return cls.model_validate(item, from_attributes=True)


class StaffAccessOut(StaffOut):
    scopes: list[str]
    role_ids: list[int]
    effective_scopes: list[str]

    @classmethod
    def from_access(cls, item: StaffAccess) -> "StaffAccessOut":
        return cls(
            **StaffOut.from_model(item.staff).model_dump(),
            scopes=sorted(item.scopes),
            role_ids=[role.id for role in item.roles],
            effective_scopes=sorted(item.effective_scopes),
        )


class StaffScopeCatalog(BaseModel):
    areas: list[str]
    levels: list[str]


@router.get("/scope-catalog")
async def scope_catalog() -> APIResponse[StaffScopeCatalog, None]:
    """Read supported administrative capabilities."""
    return APIResponse.from_data(
        StaffScopeCatalog(
            areas=list(STAFF_SCOPE_AREAS), levels=list(STAFF_SCOPE_LEVELS)
        )
    )


@router.get("")
async def page(
    data: Annotated[StaffSearch, Query()],
    service: FromDishka[IStaffAdministration],
) -> APIResponse[StaffOut, BaseMeta]:
    """Search staff without exposing credential hashes."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[StaffOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}")
async def detail(
    id: int, service: FromDishka[IStaffAdministration]
) -> APIResponse[StaffAccessOut, None]:
    """Read the selected staff account and current grants."""
    result = await service.get(id)
    return APIResponse.from_data(StaffAccessOut.from_access(result))


@router.post("")
async def create(
    data: StaffCreate,
    principal: Annotated[Principal, scoped("staff")],
    service: FromDishka[IStaffAdministration],
) -> APIResponse[StaffAccessOut, None]:
    """Create a staff account within the actor's authority."""
    result = await service.create(data, principal.staff_id)
    return APIResponse.from_data(StaffAccessOut.from_access(result))


@router.put("/{id:int}/access")
async def access(
    id: int,
    data: StaffAccessWrite,
    principal: Annotated[Principal, scoped("staff")],
    service: FromDishka[IStaffAdministration],
) -> APIResponse[StaffAccessOut, None]:
    """Update current grants and activation with stale-edit protection."""
    result = await service.update_access(id, data, principal.staff_id)
    return APIResponse.from_data(StaffAccessOut.from_access(result))


@router.put("/{id:int}/password")
async def password(
    id: int,
    data: StaffPasswordWrite,
    principal: Annotated[Principal, scoped("staff")],
    service: FromDishka[IStaffAdministration],
) -> Response:
    """Reset a password and invalidate the account's sessions."""
    await service.reset_password(id, data, principal.staff_id)
    return Response(status_code=204)
