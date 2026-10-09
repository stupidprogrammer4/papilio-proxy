"""Owned customer checkout offers, commands and durable outcomes."""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.customer_auth.config.dependencies import (
    CurrentCustomer,
    WritableCustomer,
)
from src.modules.sales.checkout.domain.attempts import (
    CheckoutRetire,
    CheckoutRetirement,
)
from src.modules.sales.checkout.domain.contracts import (
    CheckoutCancel,
    CheckoutCreate,
    CheckoutOffer,
    CheckoutRead,
    CheckoutReconfirm,
    CheckoutSearch,
)
from src.modules.sales.checkout.interfaces import (
    ICheckoutIntentCommand,
    ICheckoutOfferQuery,
    ICheckoutQuery,
    ICheckoutRetirementCommand,
    ICheckoutTaskPublisher,
)

router = APIRouter(
    prefix="/v1/customer/checkouts",
    tags=["Customer Checkout"],
    route_class=DishkaRoute,
)


@router.post("/retire")
async def retire(
    data: CheckoutRetire,
    principal: WritableCustomer,
    command: FromDishka[ICheckoutRetirementCommand],
) -> APIResponse[CheckoutRetirement, None]:
    result = await command.retire(principal.customer_id, data)
    return APIResponse.from_data(result)


@router.get("/offers/{plan_id:int}")
async def offer(
    plan_id: int,
    principal: CurrentCustomer,
    query: FromDishka[ICheckoutOfferQuery],
) -> APIResponse[CheckoutOffer, None]:
    result = await query.get(principal.customer_id, plan_id)
    return APIResponse.from_data(result)


@router.get("/{id:int}")
async def detail(
    id: int, principal: CurrentCustomer, query: FromDishka[ICheckoutQuery]
) -> APIResponse[CheckoutRead, None]:
    result = await query.get(principal.customer_id, id)
    return APIResponse.from_data(result)


@router.post("")
async def create(
    data: CheckoutCreate,
    principal: WritableCustomer,
    command: FromDishka[ICheckoutIntentCommand],
    publisher: FromDishka[ICheckoutTaskPublisher],
) -> APIResponse[CheckoutRead, None]:
    result = await command.create(principal.customer_id, data)
    # The native command's outer transaction has committed at this boundary.
    await publisher.enqueue(result.id)
    return APIResponse.from_data(
        CheckoutRead.model_validate(result, from_attributes=True)
    )


@router.post("/{id:int}/reconfirm")
async def reconfirm(
    id: int,
    data: CheckoutReconfirm,
    principal: WritableCustomer,
    command: FromDishka[ICheckoutIntentCommand],
    publisher: FromDishka[ICheckoutTaskPublisher],
) -> APIResponse[CheckoutRead, None]:
    result = await command.reconfirm(principal.customer_id, id, data)
    await publisher.enqueue(result.id)
    return APIResponse.from_data(
        CheckoutRead.model_validate(result, from_attributes=True)
    )


@router.post("/{id:int}/cancel")
async def cancel(
    id: int,
    data: CheckoutCancel,
    principal: WritableCustomer,
    command: FromDishka[ICheckoutIntentCommand],
) -> APIResponse[CheckoutRead, None]:
    result = await command.cancel(principal.customer_id, id, data)
    return APIResponse.from_data(
        CheckoutRead.model_validate(result, from_attributes=True)
    )


@router.get("")
async def history(
    principal: CurrentCustomer,
    data: Annotated[CheckoutSearch, Query()],
    query: FromDishka[ICheckoutQuery],
) -> APIResponse[CheckoutRead, BaseMeta]:
    result = await query.search(principal.customer_id, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
