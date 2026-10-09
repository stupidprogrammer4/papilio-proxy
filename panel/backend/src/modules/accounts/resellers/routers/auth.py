from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Request, Response
from papilio.api.dependencies.rate_limit import (
    by_body_field,
    by_ip,
    rate_limit,
)
from pydantic import BaseModel

from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.config.dependencies import (
    COOKIE,
    CurrentReseller,
    WritableReseller,
    origin_allowed,
)
from src.modules.accounts.resellers.domain.dtos import ResellerCredentials
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.accounts.resellers.interfaces import IResellerAuthCommand

router = APIRouter(
    prefix="/v1/reseller/auth", tags=["Reseller Auth"], route_class=DishkaRoute
)


class ResellerSessionOut(BaseModel):
    reseller_id: int
    account_id: int
    title: str
    username: str
    scopes: list[str]
    csrf_token: str


def view(principal: ResellerPrincipal) -> ResellerSessionOut:
    return ResellerSessionOut(
        reseller_id=principal.reseller_id,
        account_id=principal.account_id,
        title=principal.title,
        username=principal.username,
        scopes=sorted(principal.scopes),
        csrf_token=principal.csrf_token,
    )


@router.post(
    "/login",
    dependencies=[
        rate_limit(
            "papilio_reseller_login_ip", parts=(by_ip,), closed_when_down=True
        ),
        rate_limit(
            "papilio_reseller_login_account",
            parts=(by_body_field("username"),),
            closed_when_down=True,
        ),
    ],
)
async def login(
    data: ResellerCredentials,
    request: Request,
    response: Response,
    command: FromDishka[IResellerAuthCommand],
    settings: FromDishka[PapilioSettings],
) -> ResellerSessionOut:
    """Authenticate a reseller account in its separate cookie realm."""
    if not origin_allowed(request.headers.get("origin", ""), settings):
        raise HTTPException(403, "درخواست از مبدأ مجاز نیست.")
    issued = await command.login(data)
    capacity = settings.resellers
    assert capacity is not None
    response.set_cookie(
        COOKIE,
        issued.token,
        max_age=capacity.session_seconds,
        httponly=True,
        secure=capacity.portal_origin.startswith("https://"),
        samesite="strict",
        path="/",
    )
    return view(issued.principal)


@router.get("/me")
async def me(principal: CurrentReseller) -> ResellerSessionOut:
    """Read the current reseller identity and actual scopes."""
    return view(principal)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    _: WritableReseller,
    command: FromDishka[IResellerAuthCommand],
) -> Response:
    """Revoke the current reseller session."""
    await command.logout(request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response
