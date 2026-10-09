import json
from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel, field_validator

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.dtos import StaffSearch
from src.modules.accounts.staff.domain.results import Principal
from src.modules.accounts.staff.domain.roles import (
    RoleCreate,
    RoleHistorySearch,
    RoleModel,
    RoleRevisionModel,
    RoleSearch,
    RoleValues,
    RoleWrite,
    StaffRoleChangeModel,
    StaffRoleWrite,
)
from src.modules.accounts.staff.interfaces import (
    IRoleCommand,
    IRoleHistoryQuery,
    IRoleMemberQuery,
    IRoleQuery,
    IStaffAdministration,
    IStaffRoleCommand,
    IStaffRoleHistoryQuery,
)
from src.modules.accounts.staff.routers.admin import StaffAccessOut, StaffOut

router = APIRouter(
    prefix="/v1/admin",
    tags=["Staff Roles"],
    route_class=DishkaRoute,
    dependencies=[scoped("staff")],
)


class RoleOut(RoleValues):
    id: int
    code: str
    revision: int

    @classmethod
    def from_model(cls, row: RoleModel) -> "RoleOut":
        return cls(
            id=row.id,
            code=row.code,
            title=row.title,
            is_active=row.is_active,
            scopes=json.loads(row.scopes_json),
            revision=row.revision,
        )


class AuditOut(BaseModel):
    id: int
    created_at: datetime
    reason: str

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class RoleRevisionOut(AuditOut, RoleValues):
    revision: int
    staff_id: int

    @classmethod
    def from_model(cls, row: RoleRevisionModel) -> "RoleRevisionOut":
        assert row.created_at is not None
        return cls(
            id=row.id,
            created_at=row.created_at,
            reason=row.reason,
            revision=row.revision,
            staff_id=row.staff_id,
            title=row.title,
            is_active=row.is_active,
            scopes=json.loads(row.scopes_json),
        )


class StaffRoleChangeOut(AuditOut):
    target_staff_id: int
    actor_staff_id: int
    previous_role_ids: list[int]
    role_ids: list[int]

    @classmethod
    def from_model(cls, row: StaffRoleChangeModel) -> "StaffRoleChangeOut":
        assert row.created_at is not None
        return cls(
            id=row.id,
            created_at=row.created_at,
            reason=row.reason,
            target_staff_id=row.target_staff_id,
            actor_staff_id=row.actor_staff_id,
            previous_role_ids=json.loads(row.previous_json),
            role_ids=json.loads(row.current_json),
        )


@router.get("/roles")
async def search(
    data: Annotated[RoleSearch, Query()], service: FromDishka[IRoleQuery]
) -> APIResponse[RoleOut, BaseMeta]:
    """Search named roles and retain selected IDs across pages."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[RoleOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/roles/{id:int}")
async def detail(
    id: int, service: FromDishka[IRoleQuery]
) -> APIResponse[RoleOut, None]:
    """Read current role authority and revision."""
    result = await service.get(id)
    return APIResponse.from_data(RoleOut.from_model(result))


@router.post("/roles")
async def create(
    data: RoleCreate,
    principal: Annotated[Principal, scoped("staff")],
    command: FromDishka[IRoleCommand],
) -> APIResponse[RoleOut, None]:
    """Create a named role within current actor authority."""
    result = await command.create(data, principal.staff_id)
    return APIResponse.from_data(RoleOut.from_model(result))


@router.put("/roles/{id:int}")
async def update(
    id: int,
    data: RoleWrite,
    principal: Annotated[Principal, scoped("staff")],
    command: FromDishka[IRoleCommand],
) -> APIResponse[RoleOut, None]:
    """Revise role grants or activation with stale-edit protection."""
    result = await command.update(id, data, principal.staff_id)
    return APIResponse.from_data(RoleOut.from_model(result))


@router.get("/roles/{id:int}/history")
async def history(
    id: int,
    data: Annotated[RoleHistorySearch, Query()],
    query: FromDishka[IRoleQuery],
    service: FromDishka[IRoleHistoryQuery],
) -> APIResponse[RoleRevisionOut, BaseMeta]:
    """Read immutable revisions for an existing role."""
    await query.get(id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[RoleRevisionOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.put("/staff/{id:int}/roles")
async def assign(
    id: int,
    data: StaffRoleWrite,
    principal: Annotated[Principal, scoped("staff")],
    command: FromDishka[IStaffRoleCommand],
) -> APIResponse[StaffAccessOut, None]:
    """Add, remove or replace the selected account's role membership."""
    result = await command.update(id, data, principal.staff_id)
    return APIResponse.from_data(StaffAccessOut.from_access(result))


@router.get("/staff/{id:int}/roles/history")
async def assignment_history(
    id: int,
    data: Annotated[RoleHistorySearch, Query()],
    query: FromDishka[IStaffAdministration],
    service: FromDishka[IStaffRoleHistoryQuery],
) -> APIResponse[StaffRoleChangeOut, BaseMeta]:
    """Read immutable changes for the selected staff account."""
    await query.get(id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[StaffRoleChangeOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/roles/{id:int}/members")
async def members(
    id: int,
    data: Annotated[StaffSearch, Query()],
    query: FromDishka[IRoleQuery],
    service: FromDishka[IRoleMemberQuery],
) -> APIResponse[StaffOut, BaseMeta]:
    """Search accounts assigned to the selected role."""
    await query.get(id)
    result = await service.search(id, data)
    return APIResponse(
        success=True,
        data=[StaffOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
