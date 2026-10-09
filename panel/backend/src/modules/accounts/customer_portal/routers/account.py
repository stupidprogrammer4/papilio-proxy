from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.customer_auth.config.dependencies import (
    CurrentCustomer,
    WritableCustomer,
)
from src.modules.accounts.customer_portal.domain.dtos import (
    CustomerPage,
    CustomerPurchase,
    CustomerTopupCreate,
)
from src.modules.accounts.customer_portal.interfaces import (
    ICustomerAccountCommand,
)
from src.modules.billing.destinations.domain.dtos import (
    CheckoutPolicy,
    DestinationSearch,
)
from src.modules.billing.destinations.domain.results import (
    DestinationDetails,
)
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)
from src.modules.billing.receipts.domain.dtos import ReceiptPolicy
from src.modules.billing.wallet.domain.dtos import WalletLedgerSearch
from src.modules.billing.wallet.domain.results import (
    TopupPaymentInstructionRead,
)
from src.modules.billing.wallet.interfaces import (
    ITopupInstructionQuery,
    IWalletCommand,
    IWalletLedgerQuery,
)
from src.modules.billing.wallet.routers.schemas import (
    TopupOut,
    WalletBalanceOut,
    WalletEntryOut,
)
from src.modules.bot.domain.results import BotDelivery
from src.modules.network.ip_limits.interfaces import IIpPolicyProjectionQuery
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.attention.domain.renewal import (
    CustomerRenewalEligibility,
)
from src.modules.sales.attention.interfaces import (
    ICustomerRenewalEligibilityQuery,
)
from src.modules.sales.catalog.domain.dtos import PlanSearch
from src.modules.sales.catalog.routers.schemas import PlanOut
from src.modules.sales.reseller_billing.interfaces import ICustomerCatalogQuery
from src.modules.sales.subscriptions.domain.dtos import AutoRenewChoice
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand
from src.modules.sales.subscriptions.routers.schemas import SubscriptionOut

router = APIRouter(
    prefix="/v1/customer", tags=["Customer Account"], route_class=DishkaRoute
)


class CustomerBusinessOut(BaseModel):
    receipts: ReceiptPolicy | None
    brand_title: str
    payment_instructions: str | None
    support_handle: str | None
    topup_options_rial: list[int]
    checkout: CheckoutPolicy | None


@router.get("/preferences")
async def preferences(
    _: CurrentCustomer, service: FromDishka[IPreferencesService]
) -> APIResponse[CustomerBusinessOut, None]:
    result = await service.current()
    return APIResponse.from_data(
        CustomerBusinessOut.model_validate(result.values, from_attributes=True)
    )


@router.get("/wallet")
async def balance(
    principal: CurrentCustomer, command: FromDishka[IWalletCommand]
) -> APIResponse[WalletBalanceOut, None]:
    result = await command.balance(principal.customer_id)
    return APIResponse.from_data(
        WalletBalanceOut(
            customer_id=principal.customer_id, balance_rial=result
        )
    )


@router.get("/wallet/entries")
async def entries(
    principal: CurrentCustomer,
    data: Annotated[WalletLedgerSearch, Query()],
    query: FromDishka[IWalletLedgerQuery],
) -> APIResponse[WalletEntryOut, BaseMeta]:
    result = await query.search(principal.customer_id, data)
    return APIResponse(
        success=True,
        data=[WalletEntryOut.from_facts(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/payment-destinations")
async def destinations(
    _: CurrentCustomer,
    data: Annotated[DestinationSearch, Query()],
    service: FromDishka[IPaymentDestinationService],
) -> APIResponse[DestinationDetails, BaseMeta]:
    result = await service.search(data, customer=True)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/topups")
async def request_topup(
    principal: WritableCustomer,
    data: CustomerTopupCreate,
    command: FromDishka[ICustomerAccountCommand],
) -> APIResponse[TopupOut, None]:
    result = await command.request_topup(principal.customer_id, data)
    return APIResponse.from_data(TopupOut.from_model(result))


@router.get("/topups")
async def topups(
    principal: CurrentCustomer,
    data: Annotated[CustomerPage, Query()],
    command: FromDishka[ICustomerAccountCommand],
) -> APIResponse[TopupOut, BaseMeta]:
    result = await command.topups(principal.customer_id, data)
    return APIResponse(
        success=True,
        data=[TopupOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/topups/{id:int}")
async def topup(
    principal: CurrentCustomer,
    id: int,
    command: FromDishka[ICustomerAccountCommand],
) -> APIResponse[TopupOut, None]:
    result = await command.topup(principal.customer_id, id)
    return APIResponse.from_data(TopupOut.from_model(result))


@router.get("/topups/{id:int}/instruction")
async def instruction(
    principal: CurrentCustomer,
    id: int,
    query: FromDishka[ITopupInstructionQuery],
) -> APIResponse[TopupPaymentInstructionRead, None]:
    result = await query.get(id, principal.customer_id)
    return APIResponse(success=True, data=[] if result is None else [result])


@router.get("/plans")
async def plans(
    principal: CurrentCustomer,
    data: Annotated[PlanSearch, Query()],
    service: FromDishka[ICustomerCatalogQuery],
) -> APIResponse[PlanOut, BaseMeta]:
    result = await service.search(principal.customer_id, data)
    return APIResponse(
        success=True,
        data=[PlanOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/subscriptions")
async def purchase(
    principal: WritableCustomer,
    data: CustomerPurchase,
    command: FromDishka[ICustomerAccountCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, None]:
    result = await command.purchase(principal.customer_id, data)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(SubscriptionOut.from_model(result, ip_policy))


@router.get("/subscriptions")
async def subscriptions(
    principal: CurrentCustomer,
    data: Annotated[CustomerPage, Query()],
    command: FromDishka[ICustomerAccountCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, BaseMeta]:
    result = await command.subscriptions_page(principal.customer_id, data)
    ip_policies = await ip_projection.many([item.id for item in result.items])
    return APIResponse(
        success=True,
        data=[
            SubscriptionOut.from_model(row, ip_policies[row.id])
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.patch("/subscriptions/{id:int}/auto-renew")
async def renewal(
    principal: WritableCustomer,
    id: int,
    data: AutoRenewChoice,
    command: FromDishka[ISubscriptionCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, None]:
    result = await command.customer_set_auto_renew(
        id, principal.customer_id, data
    )
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(SubscriptionOut.from_model(result, ip_policy))


@router.get("/subscriptions/{id:int}/delivery")
async def delivery(
    principal: CurrentCustomer,
    id: int,
    command: FromDishka[ICustomerAccountCommand],
) -> APIResponse[BotDelivery, None]:
    result = await command.delivery(principal.customer_id, id, False)
    return APIResponse.from_data(result)


@router.post("/subscriptions/{id:int}/rotate-link")
async def rotate(
    principal: WritableCustomer,
    id: int,
    command: FromDishka[ICustomerAccountCommand],
) -> APIResponse[BotDelivery, None]:
    result = await command.delivery(principal.customer_id, id, True)
    return APIResponse.from_data(result)


@router.get("/subscriptions/{id:int}")
async def subscription(
    principal: CurrentCustomer,
    id: int,
    command: FromDishka[ICustomerAccountCommand],
    ip_projection: FromDishka[IIpPolicyProjectionQuery],
) -> APIResponse[SubscriptionOut, None]:
    """Read one owned service without selecting the customer again."""
    result = await command.subscription(principal.customer_id, id)
    ip_policy = await ip_projection.single(result.id)
    return APIResponse.from_data(SubscriptionOut.from_model(result, ip_policy))


@router.get("/plans/{id:int}")
async def plan_detail(
    principal: CurrentCustomer,
    id: int,
    service: FromDishka[ICustomerCatalogQuery],
) -> APIResponse[PlanOut, None]:
    """Refresh the known purchase choice before confirming its price."""
    result = await service.get(principal.customer_id, id)
    return APIResponse.from_data(PlanOut.from_model(result))


@router.get("/subscriptions/{id:int}/renewal-eligibility")
async def renewal_eligibility(
    principal: CurrentCustomer,
    id: int,
    query: FromDishka[ICustomerRenewalEligibilityQuery],
) -> APIResponse[CustomerRenewalEligibility, None]:
    result = await query.get(id, principal.customer_id)
    return APIResponse.from_data(result)
