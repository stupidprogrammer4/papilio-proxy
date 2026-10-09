from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.resellers.config.dependencies import scoped
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.network.ip_limits.interfaces import IIpPolicyProjectionQuery
from src.modules.sales.reseller_billing.domain.dtos import (
    PurchaseActor,
    ResellerSubscriptionPurchase,
)
from src.modules.sales.reseller_billing.interfaces import (
    IResellerSubscriptionQuery,
)
from src.modules.sales.reseller_billing.routers.schemas import (
    BillingSubscriptionOut,
)
from src.modules.sales.subscriptions.domain.dtos import (
    AutoRenewChoice,
    SubscriptionSearch,
)
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand

router = APIRouter(
    prefix="/v1/reseller/subscriptions",
    tags=["Reseller Sales"],
    route_class=DishkaRoute,
)


@router.post("")
async def purchase(
    data: ResellerSubscriptionPurchase,
    principal: Annotated[ResellerPrincipal, scoped("subscriptions", "create")],
    command: FromDishka[ISubscriptionCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Purchase for an owned customer using an explicitly selected wallet."""
    result = await command.purchase(
        data,
        actor=PurchaseActor(reseller=principal, payer_mode=data.payer_mode),
    )
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.get("")
async def page(
    data: Annotated[SubscriptionSearch, Query()],
    principal: Annotated[ResellerPrincipal, scoped("subscriptions", "read")],
    query: FromDishka[IResellerSubscriptionQuery],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, BaseMeta]:
    """Search subscriptions belonging to this organization's customers."""
    result = await query.search(principal.reseller_id, data)
    ip_policies = await ip_projection.many([item.id for item in result.items])
    return APIResponse(
        success=True,
        data=[
            BillingSubscriptionOut.from_model(row, ip_policies[row.id])
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}")
async def detail(
    id: int,
    principal: Annotated[ResellerPrincipal, scoped("subscriptions", "read")],
    query: FromDishka[IResellerSubscriptionQuery],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Read a subscription while retaining its customer's ownership."""
    result = await query.get(principal.reseller_id, id)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.patch("/{id:int}/auto-renew")
async def auto_renew(
    id: int,
    data: AutoRenewChoice,
    principal: Annotated[ResellerPrincipal, scoped("subscriptions", "update")],
    command: FromDishka[ISubscriptionCommand],
    query: FromDishka[IResellerSubscriptionQuery],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Change automatic renewal for the selected owned subscription."""
    await query.get(principal.reseller_id, id)
    result = await command.reseller_set_auto_renew(id, principal, data)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )
