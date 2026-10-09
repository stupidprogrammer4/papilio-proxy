from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal
from src.modules.network.ip_limits.interfaces import IIpPolicyProjectionQuery
from src.modules.sales.reseller_billing.domain.dtos import (
    AdminSubscriptionPurchase,
    PurchaseActor,
)
from src.modules.sales.reseller_billing.routers.schemas import (
    BillingSubscriptionOut,
)
from src.modules.sales.subscriptions.domain.dtos import (
    AutoRenewChoice,
    ProvisionFailure,
    SubscriptionControlSearch,
    SubscriptionResume,
    SubscriptionSearch,
    SubscriptionSuspend,
)
from src.modules.sales.subscriptions.interfaces import (
    ISubscriptionCommand,
    ISubscriptionControlCommand,
    ISubscriptionControlQuery,
    ISubscriptionLifecycleCommand,
)
from src.modules.sales.subscriptions.routers.schemas import (
    SubscriptionControlOut,
)

router = APIRouter(
    prefix="/v1/admin/subscriptions",
    tags=["Admin Subscriptions"],
    route_class=DishkaRoute,
    dependencies=[scoped("subscriptions")],
)


@router.get("")
async def page(
    data: Annotated[SubscriptionSearch, Query()],
    command: FromDishka[ISubscriptionCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, BaseMeta]:
    """Search subscriptions and renewal states."""
    result = await command.search(data)
    ip_policies = await ip_projection.many([item.id for item in result.items])
    return APIResponse(
        success=True,
        data=[
            BillingSubscriptionOut.from_model(item, ip_policies[item.id])
            for item in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("")
async def purchase(
    data: AdminSubscriptionPurchase,
    principal: Annotated[Principal, scoped("subscriptions", "create")],
    command: FromDishka[ISubscriptionCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Debit a wallet and create an entitlement pending provisioning."""
    result = await command.purchase(
        data,
        actor=PurchaseActor(
            staff_id=principal.staff_id, payer_mode=data.payer_mode
        ),
    )
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.get("/{id:int}")
async def detail(
    id: int,
    command: FromDishka[ISubscriptionCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Read one subscription and retain its customer context."""
    result = await command.get(id)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.post(
    "/{id:int}/check-lifecycle",
)
async def check_lifecycle(
    id: int,
    command: FromDishka[ISubscriptionLifecycleCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Request expiry/quota revocation without refunding consumed service."""
    result = await command.check(id)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.patch("/{id:int}/auto-renew")
async def auto_renew(
    id: int,
    data: AutoRenewChoice,
    command: FromDishka[ISubscriptionCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Enable or disable automatic renewal for one subscription."""
    result = await command.set_auto_renew(id, data)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.post("/{id:int}/provision-failed")
async def provision_failed(
    id: int,
    data: ProvisionFailure,
    principal: Annotated[Principal, scoped("subscriptions")],
    command: FromDishka[ISubscriptionCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Refund a paid subscription after verified provisioning failure."""
    result = await command.fail_provision(id, data, principal.staff_id)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.put("/{id:int}/suspension")
async def suspend(
    id: int,
    data: SubscriptionSuspend,
    principal: Annotated[Principal, scoped("subscriptions")],
    command: FromDishka[ISubscriptionControlCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Stop delivery and request acknowledged node revocation."""
    result = await command.suspend(id, data, principal.staff_id)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.put("/{id:int}/resumption")
async def resume(
    id: int,
    data: SubscriptionResume,
    principal: Annotated[Principal, scoped("subscriptions")],
    command: FromDishka[ISubscriptionControlCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[BillingSubscriptionOut, None]:
    """Resume an unconsumed, fully revoked subscription without charging."""
    result = await command.resume(id, data, principal.staff_id)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(
        BillingSubscriptionOut.from_model(result, ip_policy)
    )


@router.get("/{id:int}/controls")
async def controls(
    id: int,
    data: Annotated[SubscriptionControlSearch, Query()],
    query: FromDishka[ISubscriptionControlQuery],
) -> APIResponse[SubscriptionControlOut, BaseMeta]:
    """Read the selected subscription's suspension and resumption history."""
    result = await query.search(id, data)
    return APIResponse(
        success=True,
        data=[
            SubscriptionControlOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
