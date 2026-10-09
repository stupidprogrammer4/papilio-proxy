from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from papilio.errors.exceptions import ForbiddenException
from pydantic import BaseModel, field_validator

from src.modules.accounts.staff.config.dependencies import CurrentStaff, scoped
from src.modules.accounts.staff.domain.results import Principal
from src.modules.operations.automation.domain.dtos import (
    ScheduleHistorySearch,
    ScheduleKey,
    SchedulePolicy,
    ScheduleWrite,
)
from src.modules.operations.automation.domain.models import (
    AutomationRevisionModel,
)
from src.modules.operations.automation.domain.results import AutomationSchedule
from src.modules.operations.automation.interfaces import (
    IAutomationHistoryQuery,
    IAutomationPolicyCommand,
    IAutomationPolicyQuery,
)
from src.modules.operations.automation.tasks.schedulers.registrations import (
    ReconcileAutomationSchedule,
)

router = APIRouter(
    prefix="/v1/admin/automation", tags=["Automation"], route_class=DishkaRoute
)


class AutomationScheduleOut(SchedulePolicy):
    key: ScheduleKey
    scope: str
    revision: int
    applied_revision: int | None
    registered_at: datetime | None
    capacity_valid: bool

    @field_validator("registered_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        return (
            None
            if value is None
            else value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value
        )

    @classmethod
    def from_schedule(
        cls, item: AutomationSchedule
    ) -> "AutomationScheduleOut":
        return cls(
            **item.values.model_dump(),
            key=item.key,
            scope=item.scope,
            revision=item.revision,
            applied_revision=item.applied_revision,
            registered_at=item.registered_at,
            capacity_valid=item.capacity_valid,
        )


class AutomationRevisionOut(BaseModel):
    revision: int
    values: SchedulePolicy
    reason: str
    staff_id: int
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @classmethod
    def from_model(
        cls, row: AutomationRevisionModel
    ) -> "AutomationRevisionOut":
        assert row.created_at is not None
        return cls(
            revision=row.revision,
            values=SchedulePolicy.model_validate_json(row.policy_json),
            reason=row.reason,
            staff_id=row.staff_id,
            created_at=row.created_at,
        )


def visible(principal: Principal, item: AutomationSchedule) -> bool:
    return bool(
        principal.scopes & {"*", f"{item.scope}:*", f"{item.scope}:read"}
    )


def require_visible(principal: Principal, item: AutomationSchedule) -> None:
    if not visible(principal, item):
        raise ForbiddenException(
            message="دسترسی به این عملیات مجاز نیست.",
            message_code="admin_scope_denied",
        )


@router.get("/schedules")
async def schedules(
    principal: CurrentStaff, query: FromDishka[IAutomationPolicyQuery]
) -> APIResponse[AutomationScheduleOut, None]:
    """Read desired and registered schedules for accessible sections."""
    result = await query.schedules()
    return APIResponse(
        success=True,
        data=[
            AutomationScheduleOut.from_schedule(item)
            for item in result
            if visible(principal, item)
        ],
    )


@router.get("/schedules/{key}")
async def detail(
    key: ScheduleKey,
    principal: CurrentStaff,
    query: FromDishka[IAutomationPolicyQuery],
) -> APIResponse[AutomationScheduleOut, None]:
    result = await query.schedule(key)
    require_visible(principal, result)
    return APIResponse.from_data(AutomationScheduleOut.from_schedule(result))


@router.put("/schedules/{key}")
async def write(
    key: ScheduleKey,
    data: ScheduleWrite,
    principal: Annotated[Principal, scoped("settings", "update")],
    query: FromDishka[IAutomationPolicyQuery],
    command: FromDishka[IAutomationPolicyCommand],
) -> APIResponse[AutomationScheduleOut, None]:
    current = await query.schedule(key)
    require_visible(principal, current)
    result = await command.write(key, data, principal.staff_id)
    return APIResponse.from_data(AutomationScheduleOut.from_schedule(result))


@router.get("/schedules/{key}/history")
async def history(
    key: ScheduleKey,
    data: Annotated[ScheduleHistorySearch, Query()],
    principal: CurrentStaff,
    policies: FromDishka[IAutomationPolicyQuery],
    query: FromDishka[IAutomationHistoryQuery],
) -> APIResponse[AutomationRevisionOut, BaseMeta]:
    current = await policies.schedule(key)
    require_visible(principal, current)
    result = await query.search(key, data)
    return APIResponse(
        success=True,
        data=[AutomationRevisionOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/schedules/{key}/reconcile", status_code=202)
async def reconcile(
    key: ScheduleKey,
    principal: Annotated[Principal, scoped("settings", "update")],
    query: FromDishka[IAutomationPolicyQuery],
) -> dict[str, bool]:
    current = await query.schedule(key)
    require_visible(principal, current)
    await ReconcileAutomationSchedule.enqueue(key=key.value)
    return {"accepted": True}
