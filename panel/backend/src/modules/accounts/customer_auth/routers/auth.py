from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Request, Response
from papilio.api.dependencies.rate_limit import by_ip, rate_limit
from pydantic import BaseModel, Field

from src.config.settings import PapilioSettings
from src.modules.accounts.customer_auth.config.dependencies import (
    COOKIE,
    CurrentCustomer,
    WritableCustomer,
    customer_origin_allowed,
)
from src.modules.accounts.customer_auth.domain.results import CustomerPrincipal
from src.modules.accounts.customer_auth.interfaces import ICustomerAuthCommand

router = APIRouter(
    prefix="/v1/customer/auth", tags=["Customer Auth"], route_class=DishkaRoute
)


class LoginExchange(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class CustomerSessionOut(BaseModel):
    customer_id: int
    display_name: str
    csrf_token: str


def view(principal: CustomerPrincipal) -> CustomerSessionOut:
    return CustomerSessionOut(
        customer_id=principal.customer_id,
        display_name=principal.display_name,
        csrf_token=principal.csrf_token,
    )


@router.post(
    "/exchange",
    dependencies=[
        rate_limit(
            "papilio_customer_login", parts=(by_ip,), closed_when_down=True
        )
    ],
)
async def exchange(
    data: LoginExchange,
    request: Request,
    response: Response,
    auth: FromDishka[ICustomerAuthCommand],
    settings: FromDishka[PapilioSettings],
) -> CustomerSessionOut:
    """Exchange a one-use private bot link for a customer session."""
    if not customer_origin_allowed(
        request.headers.get("origin", ""), settings
    ):
        raise HTTPException(403, "درخواست از مبدأ مجاز نیست.")
    issued = await auth.exchange(data.token)
    response.set_cookie(
        COOKIE,
        issued.token,
        max_age=settings.customer_auth.session_seconds,
        httponly=True,
        secure=settings.public.customer_portal_origin.startswith("https://"),
        samesite="strict",
        path="/",
    )
    return view(issued.principal)


@router.get("/me")
async def me(principal: CurrentCustomer) -> CustomerSessionOut:
    """Read only the current customer identity."""
    return view(principal)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    _: WritableCustomer,
    auth: FromDishka[ICustomerAuthCommand],
) -> Response:
    """Revoke this customer session."""
    await auth.logout(request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response
