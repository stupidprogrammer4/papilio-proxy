from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.billing.reviews.domain.dtos import PaymentReviewSearch
from src.modules.billing.reviews.interfaces import (
    IPaymentReviewCommand,
    IPaymentReviewQuery,
)

router = APIRouter(
    prefix="/v1/admin/payments/reviews",
    tags=["Automation"],
    route_class=DishkaRoute,
)


class PaymentReviewOut(BaseModel):
    topup_id: int
    customer_id: int
    customer_name: str
    amount_rial: int
    topup_status: str
    status: str
    candidate_count: int
    competing_topup_count: int
    checked_at: datetime


class CheckOut(BaseModel):
    topup_id: int
    status: str
    checked_at: datetime


@router.get("", dependencies=[scoped("payments")])
async def page(
    data: Annotated[PaymentReviewSearch, Query()],
    query: FromDishka[IPaymentReviewQuery],
) -> APIResponse[PaymentReviewOut, BaseMeta]:
    """Search the latest recorded checks and their underlying records."""
    result = await query.search(data)
    return APIResponse(
        success=True,
        data=[
            PaymentReviewOut(
                topup_id=item.topup.id,
                customer_id=item.customer.id,
                customer_name=item.customer.display_name,
                amount_rial=item.topup.amount_rial,
                topup_status=item.topup.status,
                status=item.review.status,
                candidate_count=item.review.candidate_count,
                competing_topup_count=item.review.competing_topup_count,
                checked_at=item.review.checked_at.replace(tzinfo=UTC),
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
    "/{topup_id:int}/check", dependencies=[scoped("payments", "manage")]
)
async def check(
    topup_id: int, command: FromDishka[IPaymentReviewCommand]
) -> APIResponse[CheckOut, None]:
    """Refresh this record's latest observation."""
    result = await command.check(topup_id)
    return APIResponse.from_data(
        CheckOut(
            topup_id=result.topup_id,
            status=result.status,
            checked_at=result.checked_at.replace(tzinfo=UTC),
        )
    )
