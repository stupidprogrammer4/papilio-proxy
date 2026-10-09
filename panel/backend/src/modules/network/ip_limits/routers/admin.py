from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel, field_validator

from src.config.settings import IpLimitSettings
from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal
from src.modules.network.ip_limits.domain.dtos import (
    IpLimitChoice,
    IpManualBan,
    IpPolicyConfigureChoice,
    IpSessionSearch,
)
from src.modules.network.ip_limits.domain.models import IpSessionModel
from src.modules.network.ip_limits.domain.purchased import (
    EffectiveIpPolicyRead,
    IpPolicyTransitionRead,
    IpTransitionOptionsRead,
    PurchasedIpPolicyRead,
)
from src.modules.network.ip_limits.interfaces import (
    IIpLimitPolicyCommand,
    IIpLimitQuery,
    IIpRestrictionCommand,
)

router = APIRouter(
    prefix="/v1/admin/subscriptions/{subscription_id:int}/ip-limit",
    tags=["Subscription IP Limits"],
    route_class=DishkaRoute,
)


class IpLimitPolicyOut(IpLimitChoice):
    subscription_id: int
    transition: IpPolicyTransitionRead | None = None


class IpLimitDetailOut(BaseModel):
    purchased_ip_policy: PurchasedIpPolicyRead | None
    effective_ip_policy: EffectiveIpPolicyRead
    subscription_id: int
    policy: IpLimitPolicyOut | None
    defaults: IpLimitSettings
    transition_options: IpTransitionOptionsRead


class IpSessionOut(BaseModel):
    id: int
    subscription_id: int
    source_ip: str
    last_node_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    blocked_until: datetime | None
    block_reason: str | None
    blocked_by_staff_id: int | None

    @field_validator(
        "first_seen_at", "last_seen_at", "expires_at", "blocked_until"
    )
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )

    @classmethod
    def from_model(cls, item: IpSessionModel) -> "IpSessionOut":
        return cls.model_validate(item, from_attributes=True)


@router.get("", dependencies=[scoped("subscriptions", "read")])
async def detail(
    subscription_id: int, query: FromDishka[IIpLimitQuery]
) -> APIResponse[IpLimitDetailOut, None]:
    """Read this subscription's optional policy and configured bounds."""
    result = await query.detail(subscription_id)
    return APIResponse.from_data(
        IpLimitDetailOut(
            purchased_ip_policy=result.purchased_ip_policy,
            effective_ip_policy=result.effective_ip_policy,
            subscription_id=result.subscription_id,
            defaults=result.defaults,
            transition_options=result.transition_options,
            policy=IpLimitPolicyOut.model_validate(
                result.policy, from_attributes=True
            )
            if result.policy
            else None,
        )
    )


@router.put("", dependencies=[scoped("subscriptions", "update")])
async def configure(
    subscription_id: int,
    data: IpPolicyConfigureChoice,
    command: FromDishka[IIpLimitPolicyCommand],
    query: FromDishka[IIpLimitQuery],
) -> APIResponse[IpLimitPolicyOut, None]:
    """Configure the shared source-IP limit for this subscription."""
    result = await command.configure(subscription_id, data)
    current = await query.detail(subscription_id)
    policy = IpLimitPolicyOut.model_validate(result, from_attributes=True)
    policy.transition = current.effective_ip_policy.transition
    return APIResponse.from_data(policy)


@router.get("/sessions", dependencies=[scoped("subscriptions", "read")])
async def sessions(
    subscription_id: int,
    data: Annotated[IpSessionSearch, Query()],
    query: FromDishka[IIpLimitQuery],
) -> APIResponse[IpSessionOut, BaseMeta]:
    """Search recorded source-IP leases and timed restrictions."""
    result = await query.sessions(subscription_id, data)
    return APIResponse(
        success=True,
        data=[IpSessionOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post(
    "/sessions/{session_id:int}/ban",
    dependencies=[scoped("subscriptions", "update")],
)
async def ban(
    subscription_id: int,
    session_id: int,
    data: IpManualBan,
    principal: Annotated[Principal, scoped("subscriptions", "update")],
    command: FromDishka[IIpRestrictionCommand],
) -> APIResponse[IpSessionOut, None]:
    """Set a timed restriction on a selected subscription source IP."""
    result = await command.ban(
        subscription_id, session_id, data, principal.staff_id
    )
    return APIResponse.from_data(IpSessionOut.from_model(result))


@router.post(
    "/sessions/{session_id:int}/unban",
    dependencies=[scoped("subscriptions", "update")],
)
async def unban(
    subscription_id: int,
    session_id: int,
    command: FromDishka[IIpRestrictionCommand],
) -> APIResponse[IpSessionOut, None]:
    """Remove this source-IP restriction without reserving an active slot."""
    result = await command.unban(subscription_id, session_id)
    return APIResponse.from_data(IpSessionOut.from_model(result))
