from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.sales.attention.domain.dtos import SubscriptionAttentionSearch
from src.modules.sales.attention.interfaces import (
    ISubscriptionAttentionCommand,
    ISubscriptionAttentionQuery,
)

router = APIRouter(
    prefix="/v1/admin/subscriptions/attention",
    tags=["Automation"],
    route_class=DishkaRoute,
)


class SubscriptionAttentionOut(BaseModel):
    subscription_id: int
    customer_id: int
    customer_name: str
    subscription_status: str
    status: str
    expires_at: datetime | None
    auto_renew: bool
    payer_customer_id: int | None
    renewal_available: bool | None
    renewal_price_rial: int | None
    wallet_balance_rial: int
    checked_at: datetime


class CheckOut(BaseModel):
    subscription_id: int
    status: str
    checked_at: datetime


@router.get("", dependencies=[scoped("subscriptions")])
async def page(
    data: Annotated[SubscriptionAttentionSearch, Query()],
    query: FromDishka[ISubscriptionAttentionQuery],
) -> APIResponse[SubscriptionAttentionOut, BaseMeta]:
    """Search the latest recorded checks and their underlying records."""
    result = await query.search(data)
    return APIResponse(
        success=True,
        data=[
            SubscriptionAttentionOut(
                subscription_id=item.subscription.id,
                customer_id=item.customer.id,
                customer_name=item.customer.display_name,
                subscription_status=item.subscription.status,
                status=item.attention.status,
                expires_at=None
                if item.subscription.expires_at is None
                else item.subscription.expires_at.replace(tzinfo=UTC),
                auto_renew=item.subscription.auto_renew,
                payer_customer_id=item.attention.payer_customer_id,
                renewal_available=item.attention.renewal_available,
                renewal_price_rial=item.attention.renewal_price_rial,
                wallet_balance_rial=item.attention.wallet_balance_rial,
                checked_at=item.attention.checked_at.replace(tzinfo=UTC),
            )
            for item in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post(
    "/{subscription_id:int}/check",
    dependencies=[scoped("subscriptions", "manage")],
)
async def check(
    subscription_id: int, command: FromDishka[ISubscriptionAttentionCommand]
) -> APIResponse[CheckOut, None]:
    """Refresh this record's latest observation."""
    result = await command.check(subscription_id)
    return APIResponse.from_data(
        CheckOut(
            subscription_id=result.subscription_id,
            status=result.status,
            checked_at=result.checked_at.replace(tzinfo=UTC),
        )
    )
