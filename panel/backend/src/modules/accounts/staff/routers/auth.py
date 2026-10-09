from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Request, Response
from papilio.api.dependencies.rate_limit import (
    by_body_field,
    by_ip,
    rate_limit,
)
from pydantic import BaseModel

from src.config.origins import admin_origin_allowed
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.config.dependencies import (
    COOKIE,
    CurrentStaff,
    WritableStaff,
)
from src.modules.accounts.staff.domain.dtos import StaffCredentials
from src.modules.accounts.staff.domain.results import Principal
from src.modules.accounts.staff.interfaces import IStaffAuth

router = APIRouter(
    prefix="/v1/admin/auth", tags=["Admin Auth"], route_class=DishkaRoute
)


class SessionOut(BaseModel):
    username: str
    scopes: list[str]
    csrf_token: str


def _view(principal: Principal) -> SessionOut:
    return SessionOut(
        username=principal.username,
        scopes=sorted(principal.scopes),
        csrf_token=principal.csrf_token,
    )


@router.post(
    "/login",
    dependencies=[
        rate_limit(
            "papilio_admin_login",
            parts=(by_ip, by_body_field("username")),
            closed_when_down=True,
        )
    ],
)
async def login(
    body: StaffCredentials,
    request: Request,
    response: Response,
    auth: FromDishka[IStaffAuth],
    settings: FromDishka[PapilioSettings],
) -> SessionOut:
    """Open a short owner session from staff credentials."""
    if not admin_origin_allowed(request.headers.get("origin", ""), settings):
        raise HTTPException(403, "درخواست از مبدأ مجاز نیست.")
    issued = await auth.login(body.username, body.password.get_secret_value())
    response.set_cookie(
        COOKIE,
        issued.token,
        max_age=settings.operations.staff_session_hours * 3600,
        httponly=True,
        secure=settings.public.admin_origin.startswith("https://"),
        samesite="strict",
        path="/",
    )
    return _view(issued.principal)


@router.get("/me")
async def me(principal: CurrentStaff) -> SessionOut:
    """Read the signed-in staff identity and scopes."""
    return _view(principal)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    _: WritableStaff,
    auth: FromDishka[IStaffAuth],
) -> Response:
    """Revoke the current server-side session."""
    await auth.logout(request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response
