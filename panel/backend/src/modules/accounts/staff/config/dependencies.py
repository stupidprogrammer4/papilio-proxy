from typing import Annotated, Any

from fastapi import Depends, Request
from papilio.errors.exceptions import ForbiddenException
from papilio.security.crypto import secure_compare

from src.config.origins import admin_origin_allowed
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.domain.results import Principal
from src.modules.accounts.staff.interfaces import IStaffAuth

COOKIE = "papilio_admin"


async def current_staff(request: Request) -> Principal:
    service = await request.state.dishka_container.get(IStaffAuth)
    principal = await service.current(request.cookies.get(COOKIE, ""))
    return principal


CurrentStaff = Annotated[Principal, Depends(current_staff)]


async def _verify_write(request: Request, principal: Principal) -> None:
    settings = await request.state.dishka_container.get(PapilioSettings)
    origin = request.headers.get("origin", "")
    csrf = request.headers.get("x-csrf-token", "")
    if (
        not admin_origin_allowed(origin, settings)
        or not csrf
        or not csrf.isascii()
        or not secure_compare(csrf, principal.csrf_token)
    ):
        raise ForbiddenException(
            message="درخواست مدیریت معتبر نیست.",
            message_code="admin_csrf_denied",
        )


async def writable_staff(
    request: Request, principal: CurrentStaff
) -> Principal:
    await _verify_write(request, principal)
    return principal


WritableStaff = Annotated[Principal, Depends(writable_staff)]


_METHOD_LEVEL = {
    "GET": "read",
    "HEAD": "read",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


def scoped(scope: str, required_level: str | None = None) -> Any:
    async def guard(request: Request, principal: CurrentStaff) -> Principal:
        level = required_level or _METHOD_LEVEL.get(request.method, "manage")
        allowed = f"{scope}:{level}"
        if not (principal.scopes & {"*", f"{scope}:*", allowed}):
            raise ForbiddenException(
                message="دسترسی به این بخش مجاز نیست.",
                message_code="admin_scope_denied",
            )
        if level != "read":
            await _verify_write(request, principal)
        return principal

    return Depends(guard)
