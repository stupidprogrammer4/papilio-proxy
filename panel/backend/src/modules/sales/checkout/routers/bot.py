"""Authenticated bot checkout commands derive customer identity."""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.billing.destinations.domain.dtos import (
    CheckoutPolicy,
    DestinationSearch,
)
from src.modules.billing.destinations.domain.results import (
    DestinationDetails,
    PaymentInstruction,
)
from src.modules.bot.domain.dtos import BotIdentity
from src.modules.bot.routers.actions import bot_authorized
from src.modules.sales.checkout.domain.attempts import (
    CheckoutRetire,
    CheckoutRetirement,
)
from src.modules.sales.checkout.domain.contracts import (
    CheckoutCancel,
    CheckoutCreate,
    CheckoutLookup,
    CheckoutOffer,
    CheckoutPaymentInstructionRead,
    CheckoutRead,
    CheckoutReconfirm,
    CheckoutSearch,
)
from src.modules.sales.checkout.interfaces import ICheckoutBotCommand


class BotCheckoutCreate(BotIdentity, CheckoutCreate):
    pass


class BotCheckoutLookup(BotIdentity, CheckoutLookup):
    pass


class BotCheckoutRetire(BotIdentity, CheckoutRetire):
    pass


class BotCheckoutReconfirm(BotIdentity, CheckoutReconfirm):
    pass


class BotCheckoutCancel(BotIdentity, CheckoutCancel):
    pass


router = APIRouter(
    prefix="/v1/bot/checkouts",
    tags=["Bot Checkout"],
    route_class=DishkaRoute,
    dependencies=[Depends(bot_authorized)],
)


@router.post("/offers/{plan_id:int}")
async def offer(
    plan_id: int, data: BotIdentity, command: FromDishka[ICheckoutBotCommand]
) -> APIResponse[CheckoutOffer, None]:
    result = await command.offer(data, plan_id)
    return APIResponse.from_data(result)


@router.post("/{id:int}/status")
async def detail(
    id: int, data: BotIdentity, command: FromDishka[ICheckoutBotCommand]
) -> APIResponse[CheckoutRead, None]:
    result = await command.get(data, id)
    return APIResponse.from_data(result)


@router.post("")
async def create(
    data: BotCheckoutCreate, command: FromDishka[ICheckoutBotCommand]
) -> APIResponse[CheckoutRead, None]:
    result = await command.create(
        data, CheckoutCreate.model_validate(data.model_dump())
    )
    return APIResponse.from_data(result)


@router.post("/{id:int}/reconfirm")
async def reconfirm(
    id: int,
    data: BotCheckoutReconfirm,
    command: FromDishka[ICheckoutBotCommand],
) -> APIResponse[CheckoutRead, None]:
    result = await command.reconfirm(
        data, id, CheckoutReconfirm.model_validate(data.model_dump())
    )
    return APIResponse.from_data(result)


@router.post("/{id:int}/cancel")
async def cancel(
    id: int, data: BotCheckoutCancel, command: FromDishka[ICheckoutBotCommand]
) -> APIResponse[CheckoutRead, None]:
    result = await command.cancel(
        data, id, CheckoutCancel.model_validate(data.model_dump())
    )
    return APIResponse.from_data(result)


@router.post("/history")
async def history(
    identity: BotIdentity,
    data: Annotated[CheckoutSearch, Query()],
    command: FromDishka[ICheckoutBotCommand],
) -> APIResponse[CheckoutRead, BaseMeta]:
    result = await command.search(identity, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/lookup")
async def lookup(
    data: BotCheckoutLookup,
    command: FromDishka[ICheckoutBotCommand],
) -> APIResponse[CheckoutRead, None]:
    result = await command.lookup(
        data, CheckoutLookup.model_validate(data.model_dump())
    )
    return APIResponse.from_data(result)


@router.post("/retire")
async def retire(
    data: BotCheckoutRetire,
    command: FromDishka[ICheckoutBotCommand],
) -> APIResponse[CheckoutRetirement, None]:
    result = await command.retire(
        data, CheckoutRetire.model_validate(data.model_dump())
    )
    return APIResponse.from_data(result)


@router.post("/funding")
async def funding(
    data: BotIdentity,
    command: FromDishka[ICheckoutBotCommand],
) -> APIResponse[CheckoutPolicy, None]:
    result = await command.funding(data)
    return APIResponse.from_data(result)


@router.post("/destinations")
async def destinations(
    identity: BotIdentity,
    data: Annotated[DestinationSearch, Query()],
    command: FromDishka[ICheckoutBotCommand],
) -> APIResponse[DestinationDetails, BaseMeta]:
    result = await command.destinations(identity, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/destinations/{id:int}/instruction")
async def instruction(
    id: int,
    data: BotIdentity,
    command: FromDishka[ICheckoutBotCommand],
) -> APIResponse[PaymentInstruction, None]:
    result = await command.instruction(data, id)
    return APIResponse.from_data(result)


@router.post("/{id:int}/payment-instruction")
async def payment_instruction(
    id: int,
    data: BotIdentity,
    command: FromDishka[ICheckoutBotCommand],
) -> APIResponse[CheckoutPaymentInstructionRead | None, None]:
    result = await command.payment_instruction(data, id)
    return APIResponse.from_data(result)
