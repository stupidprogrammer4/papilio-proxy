from typing import Annotated

from fastapi import Depends, Request
from papilio.errors.exceptions import ForbiddenException
from papilio.security.crypto import secure_compare

from src.config.settings import PapilioSettings
from src.modules.accounts.customer_auth.domain.results import CustomerPrincipal
from src.modules.accounts.customer_auth.interfaces import ICustomerAuthCommand

COOKIE = "papilio_customer"


def customer_origin_allowed(origin: str, settings: PapilioSettings) -> bool:
    return (
        bool(origin)
        and origin.isascii()
        and settings.public.customer_portal_origin.isascii()
        and secure_compare(origin, settings.public.customer_portal_origin)
    )


async def current_customer(request: Request) -> CustomerPrincipal:
    auth = await request.state.dishka_container.get(ICustomerAuthCommand)
    principal = await auth.current(request.cookies.get(COOKIE, ""))
    return principal


CurrentCustomer = Annotated[CustomerPrincipal, Depends(current_customer)]


async def writable_customer(
    request: Request, principal: CurrentCustomer
) -> CustomerPrincipal:
    settings = await request.state.dishka_container.get(PapilioSettings)
    csrf = request.headers.get("x-csrf-token", "")
    if (
        not customer_origin_allowed(
            request.headers.get("origin", ""), settings
        )
        or not csrf
        or not csrf.isascii()
        or not secure_compare(csrf, principal.csrf_token)
    ):
        raise ForbiddenException(
            message="درخواست حساب مشتری معتبر نیست.",
            message_code="customer_csrf_denied",
        )
    return principal


WritableCustomer = Annotated[CustomerPrincipal, Depends(writable_customer)]
