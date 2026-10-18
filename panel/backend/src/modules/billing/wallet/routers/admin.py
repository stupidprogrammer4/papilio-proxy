from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal
from src.modules.billing.wallet.domain.dtos import (
    TopupApproval,
    TopupCreate,
    TopupRejection,
    TopupSearch,
    WalletLedgerSearch,
)
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
from src.modules.sales.checkout.interfaces import ICheckoutFundingPublisher

router = APIRouter(
    prefix="/v1/admin/payments",
    tags=["Admin Payments"],
    route_class=DishkaRoute,
    dependencies=[scoped("payments")],
)


@router.get("/wallets/{customer_id:int}/entries")
async def entries(
    customer_id: int,
    data: Annotated[WalletLedgerSearch, Query()],
    query: FromDishka[IWalletLedgerQuery],
) -> APIResponse[WalletEntryOut, BaseMeta]:
    """Read this customer's paginated credit, purchase and refund history."""
    result = await query.search(customer_id, data)
    return APIResponse(
        success=True,
        data=[WalletEntryOut.from_facts(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/topups/{id:int}")
async def detail(
    id: int, command: FromDishka[IWalletCommand]
) -> APIResponse[TopupOut, None]:
    """Read one top-up request while retaining its customer context."""
    result = await command.get_topup(id)
    return APIResponse.from_data(TopupOut.from_model(result))


@router.get("/topups")
async def page(
    data: Annotated[TopupSearch, Query()], command: FromDishka[IWalletCommand]
) -> APIResponse[TopupOut, BaseMeta]:
    """Review paginated wallet top-up requests."""
    result = await command.search(data)
    return APIResponse(
        success=True,
        data=[TopupOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/topups")
async def create(
    data: TopupCreate, command: FromDishka[IWalletCommand]
) -> APIResponse[TopupOut, None]:
    """Record a customer's top-up request."""
    result = await command.request_topup(data)
    return APIResponse.from_data(TopupOut.from_model(result))


@router.post("/topups/{id:int}/approve")
async def approve(
    id: int,
    data: TopupApproval,
    principal: Annotated[Principal, scoped("payments")],
    command: FromDishka[IWalletCommand],
    publisher: FromDishka[ICheckoutFundingPublisher],
) -> APIResponse[TopupOut, None]:
    """Credit a wallet after an owner verifies bank settlement."""
    result = await command.approve(id, data, principal.staff_id)
    await publisher.publish(result.id)
    return APIResponse.from_data(TopupOut.from_model(result))


@router.post("/topups/{id:int}/reject")
async def reject(
    id: int,
    data: TopupRejection,
    principal: Annotated[Principal, scoped("payments")],
    command: FromDishka[IWalletCommand],
) -> APIResponse[TopupOut, None]:
    """Reject a top-up request without crediting the wallet."""
    result = await command.reject(id, data, principal.staff_id)
    return APIResponse.from_data(TopupOut.from_model(result))


@router.get("/wallets/{customer_id:int}")
async def balance(
    customer_id: int, command: FromDishka[IWalletCommand]
) -> APIResponse[WalletBalanceOut, None]:
    """Read a customer's wallet balance in rial."""
    result = await command.balance(customer_id)
    return APIResponse.from_data(
        WalletBalanceOut(customer_id=customer_id, balance_rial=result)
    )


@router.get("/topups/{id:int}/instruction")
async def instruction(
    id: int, query: FromDishka[ITopupInstructionQuery]
) -> APIResponse[TopupPaymentInstructionRead, None]:
    """Read this request’s captured payment destination."""
    result = await query.get(id)
    return APIResponse(success=True, data=[] if result is None else [result])
