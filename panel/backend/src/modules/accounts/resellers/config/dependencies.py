from typing import Annotated, Any

from fastapi import Depends, Request
from papilio.errors.exceptions import ForbiddenException
from papilio.security.crypto import secure_compare

from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.accounts.resellers.interfaces import IResellerAuthQuery

COOKIE = "papilio_reseller"


def origin_allowed(origin: str, settings: PapilioSettings) -> bool:
    capacity = settings.resellers
    return (
        capacity is not None
        and bool(origin)
        and origin.isascii()
        and secure_compare(origin, capacity.portal_origin)
    )


async def current_reseller(request: Request) -> ResellerPrincipal:
    query = await request.state.dishka_container.get(IResellerAuthQuery)
    result = await query.current(request.cookies.get(COOKIE, ""))
    return result


CurrentReseller = Annotated[ResellerPrincipal, Depends(current_reseller)]


async def writable_reseller(
    request: Request,
    principal: CurrentReseller,
) -> ResellerPrincipal:
    settings = await request.state.dishka_container.get(PapilioSettings)
    csrf = request.headers.get("x-csrf-token", "")
    if (
        not origin_allowed(request.headers.get("origin", ""), settings)
        or not csrf
        or not csrf.isascii()
        or not secure_compare(csrf, principal.csrf_token)
    ):
        raise ForbiddenException(
            message="درخواست نمایندگی معتبر نیست.",
            message_code="reseller_csrf_denied",
        )
    return principal


WritableReseller = Annotated[ResellerPrincipal, Depends(writable_reseller)]


def scoped(area: str, level: str) -> Any:
    async def guard(
        request: Request,
        principal: CurrentReseller,
    ) -> ResellerPrincipal:
        if not principal.scopes & {"*", f"{area}:{level}"}:
            raise ForbiddenException(
                message="دسترسی به این بخش نمایندگی مجاز نیست.",
                message_code="reseller_scope_denied",
            )
        if level != "read":
            await writable_reseller(request, principal)
        return principal

    return Depends(guard)
