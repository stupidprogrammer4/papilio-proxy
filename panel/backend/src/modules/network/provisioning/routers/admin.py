from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel, field_validator

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.network.provisioning.domain.dtos import (
    ProvisioningRetry,
    ProvisioningSearch,
)
from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.network.provisioning.interfaces import (
    IProvisioningCommand,
    IProvisioningQuery,
)
from src.modules.sales.catalog.domain.policies import FulfillmentPolicy

router = APIRouter(
    prefix="/v1/admin/provisioning",
    tags=["Provisioning"],
    route_class=DishkaRoute,
    dependencies=[scoped("subscriptions")],
)


class RequestOut(BaseModel):
    completion: str
    id: int
    subscription_id: int
    generation: int
    state: str
    reason_code: str | None
    checked_at: datetime | None
    activated_at: datetime | None
    deadline_at: datetime
    retry_reason: str | None
    cancellation_reason: str | None
    cancelled_by_staff_id: int | None
    policy: FulfillmentPolicy

    @field_validator("checked_at", "activated_at", "deadline_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )

    @classmethod
    def from_model(cls, row: ProvisionRequestModel) -> "RequestOut":
        return cls.model_validate(
            {
                **row.model_dump(),
                "policy": FulfillmentPolicy.model_validate_json(
                    row.policy_json
                ),
            }
        )


class TaskOut(BaseModel):
    installed_revision_id: int | None
    membership_sha256: str | None
    configuration_revision: int
    id: int
    request_id: int
    configuration_id: int
    profile_id: int
    node_id: int
    action: str
    state: str
    attempts: int
    claim_until: datetime | None
    acknowledged_at: datetime | None
    error_code: str | None
    available_at: datetime

    @field_validator("claim_until", "acknowledged_at", "available_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )

    @classmethod
    def from_model(cls, row: ProvisionTaskModel) -> "TaskOut":
        return cls.model_validate(row, from_attributes=True)


@router.get("")
async def requests(
    data: Annotated[ProvisioningSearch, Query()],
    query: FromDishka[IProvisioningQuery],
) -> APIResponse[RequestOut, BaseMeta]:
    """Search durable fulfillment requests."""
    result = await query.requests(data)
    return APIResponse(
        success=True,
        data=[RequestOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}/tasks")
async def tasks(
    id: int,
    data: Annotated[ProvisioningSearch, Query()],
    query: FromDishka[IProvisioningQuery],
) -> APIResponse[TaskOut, BaseMeta]:
    """Read per-node work for the selected request."""
    result = await query.tasks(id, data)
    return APIResponse(
        success=True,
        data=[TaskOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/{id:int}/prepare")
async def prepare(
    id: int, command: FromDishka[IProvisioningCommand]
) -> APIResponse[RequestOut, None]:
    """Prepare profiles and durable node work without running a core."""
    result = await command.prepare(id, manual=True)
    return APIResponse.from_data(RequestOut.from_model(result))


@router.post("/{id:int}/retry")
async def retry(
    id: int, data: ProvisioningRetry, command: FromDishka[IProvisioningCommand]
) -> APIResponse[RequestOut, None]:
    """Retry the same paid generation without charging again."""
    result = await command.retry(id, data)
    return APIResponse.from_data(RequestOut.from_model(result))
