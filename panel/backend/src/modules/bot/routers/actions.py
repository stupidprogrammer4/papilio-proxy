from datetime import UTC, datetime
from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from papilio.security.crypto import secure_compare
from pydantic import BaseModel, Field

from src.config.settings import PapilioSettings
from src.modules.accounts.customer_auth.domain.results import CustomerLoginLink
from src.modules.billing.wallet.domain.results import (
    TopupPaymentInstructionRead,
)
from src.modules.bot.app.interfaces import IBotPresentationQuery
from src.modules.bot.domain.dtos import (
    BotAutoRenew,
    BotIdentity,
    BotPurchase,
    BotTopup,
    BotTrialClaim,
)
from src.modules.bot.domain.results import (
    BotDelivery,
    BotSupportAccess,
)
from src.modules.bot.interfaces import IBotCommand, IBotTrialCommand
from src.modules.network.ip_limits.interfaces import IIpPolicyProjectionQuery
from src.modules.operations.notifications.domain.context import (
    CheckoutNoticeAction,
    SubscriptionNoticeAction,
)
from src.modules.operations.notifications.interfaces import (
    INotificationDeliveryCommand,
)
from src.modules.sales.attention.domain.renewal import (
    CustomerRenewalEligibility,
)
from src.modules.sales.catalog.routers.schemas import PlanOut
from src.modules.sales.loyalty.domain.results import (
    CustomerPriceQuote,
    CustomerTierRead,
)
from src.modules.sales.subscriptions.routers.schemas import SubscriptionOut
from src.modules.sales.trials.domain.results import TrialAvailability


async def bot_authorized(request: Request) -> None:
    settings = await request.state.dishka_container.get(PapilioSettings)
    provided = request.headers.get("X-Papilio-Bot-Key", "")
    if (
        not provided
        or not provided.isascii()
        or not secure_compare(provided, settings.security.bot_service_key)
    ):
        raise HTTPException(401, "دسترسی بات معتبر نیست.")


router = APIRouter(
    prefix="/v1/bot",
    tags=["Bot Actions"],
    route_class=DishkaRoute,
    dependencies=[Depends(bot_authorized)],
)


class BotMenuButtonOut(BaseModel):
    action: Literal[
        "purchases",
        "loyalty",
        "trial",
        "account",
        "catalog",
        "subscriptions",
        "wallet",
        "support",
    ]
    label: str
    visible: bool


class BotPresentationOut(BaseModel):
    welcome_message: str
    welcome_photo_url: str | None
    menu_buttons: list[BotMenuButtonOut]
    message_catalog: dict[str, str]


class HomeOut(BaseModel):
    brand_title: str
    customer_id: int
    display_name: str
    balance_rial: int
    payment_instructions: str | None
    support_handle: str | None
    topup_options_rial: list[int]
    presentation: BotPresentationOut


class TopupOut(BaseModel):
    id: int
    customer_id: int
    amount_rial: int
    status: str


class PlanPageQuery(BaseModel):
    page: int = Field(default=1, ge=1)


@router.post("/home")
async def home(
    data: BotIdentity, command: FromDishka[IBotCommand]
) -> APIResponse[HomeOut, None]:
    """Resolve the Telegram customer and wallet balance."""
    result = await command.home(data)
    return APIResponse.from_data(
        HomeOut.model_validate(result, from_attributes=True)
    )


@router.get("/presentation")
async def presentation(
    query: FromDishka[IBotPresentationQuery],
    locale: Literal["fa", "en", "ru", "zh"] = Query(default="fa"),
) -> APIResponse[BotPresentationOut, None]:
    """Read the latest bot presentation settings."""
    result = await query.get(locale)
    return APIResponse.from_data(
        BotPresentationOut.model_validate(result, from_attributes=True)
    )


@router.get("/plans")
async def plans(
    data: Annotated[PlanPageQuery, Query()], command: FromDishka[IBotCommand]
) -> APIResponse[PlanOut, BaseMeta]:
    """Show active purchase choices to the bot."""
    result = await command.active_plans(data.page)
    return APIResponse(
        success=True,
        data=[PlanOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, command.page_size, result.total_items
            )
        ),
    )


@router.post("/subscriptions/search")
async def subscriptions(
    data: BotIdentity,
    command: FromDishka[IBotCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
    page: int = Query(default=1, ge=1),
) -> APIResponse[SubscriptionOut, BaseMeta]:
    """Show only subscriptions owned by this Telegram customer."""
    result = await command.my_subscriptions(data, page)
    ip_policies = await ip_projection.many([item.id for item in result.items])
    return APIResponse(
        success=True,
        data=[
            SubscriptionOut.from_model(item, ip_policies[item.id])
            for item in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                page, command.page_size, result.total_items
            )
        ),
    )


@router.post("/topups/{id:int}/payment-instruction")
async def topup_instruction(
    id: int, data: BotIdentity, command: FromDishka[IBotCommand]
) -> APIResponse[TopupPaymentInstructionRead | None, None]:
    """Read the customer's captured top-up instructions."""
    result = await command.topup_instruction(data, id)
    return APIResponse.from_data(result)


@router.post("/topups")
async def topup(
    data: BotTopup, command: FromDishka[IBotCommand]
) -> APIResponse[TopupOut, None]:
    """Request wallet credit for later owner payment review."""
    result = await command.request_topup(data)
    return APIResponse.from_data(
        TopupOut.model_validate(result, from_attributes=True)
    )


@router.post("/purchase")
async def purchase(
    data: BotPurchase,
    command: FromDishka[IBotCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, None]:
    """Purchase a plan with the customer's wallet balance."""
    result = await command.purchase(data)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(SubscriptionOut.from_model(result, ip_policy))


@router.patch("/subscriptions/{id:int}/auto-renew")
async def auto_renew(
    id: int,
    data: BotAutoRenew,
    command: FromDishka[IBotCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, None]:
    """Change renewal choice for one owned subscription."""
    result = await command.set_auto_renew(id, data)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(SubscriptionOut.from_model(result, ip_policy))


@router.post("/subscriptions/{id:int}/delivery")
async def delivery(
    id: int,
    data: BotIdentity,
    command: FromDishka[IBotCommand],
    response: Response,
) -> APIResponse[BotDelivery, None]:
    """Read private delivery links only for the owning Telegram customer."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.delivery(id, data)
    return APIResponse.from_data(result)


@router.post("/subscriptions/{id:int}/rotate-link")
async def rotate_link(
    id: int,
    data: BotIdentity,
    command: FromDishka[IBotCommand],
    response: Response,
) -> APIResponse[BotDelivery, None]:
    """Rotate the owned subscription token under customer policy."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.delivery(id, data, rotate=True)
    return APIResponse.from_data(result)


@router.post("/account-link")
async def account_link(
    data: BotIdentity, command: FromDishka[IBotCommand]
) -> APIResponse[CustomerLoginLink, None]:
    """Issue a private one-use account login link to the trusted bot."""
    result = await command.account_link(data)
    return APIResponse.from_data(result)


@router.get("/plans/{id:int}")
async def plan_detail(
    id: int, command: FromDishka[IBotCommand]
) -> APIResponse[PlanOut, None]:
    """Read an active plan before confirming its price."""
    result = await command.plan(id)
    return APIResponse.from_data(PlanOut.from_model(result))


@router.post("/customer-plans")
async def customer_plans(
    identity: BotIdentity,
    data: Annotated[PlanPageQuery, Query()],
    command: FromDishka[IBotCommand],
) -> APIResponse[PlanOut, BaseMeta]:
    """Read eligible, correctly priced choices for this bot customer."""
    result = await command.customer_plans(identity, data.page)
    return APIResponse(
        success=True,
        data=[PlanOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, command.page_size, result.total_items
            )
        ),
    )


@router.post("/customer-plans/{id:int}")
async def customer_plan(
    id: int,
    identity: BotIdentity,
    command: FromDishka[IBotCommand],
) -> APIResponse[PlanOut, None]:
    """Refresh the actual customer's allowed plan and quote."""
    result = await command.customer_plan(identity, id)
    return APIResponse.from_data(PlanOut.from_model(result))


@router.post("/support-link")
async def support_link(
    data: BotIdentity, command: FromDishka[IBotCommand]
) -> APIResponse[BotSupportAccess, None]:
    """Issue an owned private support login link."""
    result = await command.support_link(data)
    return APIResponse.from_data(result)


class NotificationSendRequest(BaseModel):
    claim_token: str = Field(
        min_length=64, max_length=64, pattern=r"^[a-f0-9]+$"
    )


class NotificationSendOut(BaseModel):
    action: SubscriptionNoticeAction | CheckoutNoticeAction | None = None
    allowed: bool
    telegram_id: int | None
    text: str | None
    lease_until: datetime | None


@router.post("/notifications/{id:int}/authorize")
async def authorize_notification(
    id: int,
    data: NotificationSendRequest,
    command: FromDishka[INotificationDeliveryCommand],
) -> APIResponse[NotificationSendOut, None]:
    """Authorize one leased send; repeated claims cannot start another send."""
    result = await command.begin_send(id, data.claim_token)
    return APIResponse.from_data(
        NotificationSendOut(
            allowed=result is not None,
            action=result.action if result else None,
            telegram_id=result.telegram_id if result else None,
            text=result.text if result else None,
            lease_until=result.lease_until.replace(tzinfo=UTC)
            if result
            else None,
        )
    )


@router.post("/trials/availability")
async def trial_availability(
    data: BotIdentity, command: FromDishka[IBotTrialCommand]
) -> APIResponse[TrialAvailability, None]:
    """Read the API-owned trial policy for this Telegram customer."""
    result = await command.availability(data)
    return APIResponse.from_data(result)


@router.post("/trials")
async def trial_claim(
    data: BotTrialClaim,
    command: FromDishka[IBotTrialCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, None]:
    """Request a free trial using the same account eligibility rules."""
    result = await command.claim(data)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(SubscriptionOut.from_model(result, ip_policy))


@router.post("/loyalty")
async def loyalty(
    data: BotIdentity, command: FromDishka[IBotCommand]
) -> APIResponse[CustomerTierRead, None]:
    """Read progress for the signed bot's Telegram identity."""
    result = await command.loyalty_status(data)
    return APIResponse.from_data(result)


@router.post("/customer-plans/{plan_id:int}/quote")
async def price_quote(
    plan_id: int, data: BotIdentity, command: FromDishka[IBotCommand]
) -> APIResponse[CustomerPriceQuote, None]:
    """Quote a plan using the Telegram customer's eligibility."""
    result = await command.price_quote(data, plan_id)
    return APIResponse.from_data(result)


@router.post("/subscriptions/{id:int}/renewal-eligibility")
async def renewal_eligibility(
    id: int, data: BotIdentity, command: FromDishka[IBotCommand]
) -> APIResponse[CustomerRenewalEligibility, None]:
    result = await command.renewal_status(data, id)
    return APIResponse.from_data(result)
