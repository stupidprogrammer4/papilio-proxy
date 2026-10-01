from __future__ import annotations

import hmac
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from bot.models.admin_web import AdminLoginDenied, AdminSession
from bot.models.branding import BrandingValidationError
from bot.models.pricing import PricingAssumptions, PricingValidationError
from bot.services.admin_plans import PlanValidationError
from bot.services.admin_web import AdminWebService
from bot.services.subscriptions import Plan, UnknownPlanError

COOKIE_NAME = "papilio_admin_session"
ASSETS = Path(__file__).resolve().parent / "static"
LOGO = Path(__file__).resolve().parents[3] / "assets" / "papilio-logo-v2.png"


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=8, max_length=256)


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=8, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=100)
    traffic_gb: int
    duration_days: int
    price_toman: int
    sort_order: int = 0
    emoji: str = "🦋"


class PricingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_days: int = Field(strict=True)
    daily_server_cost_toman: int = Field(strict=True)
    included_traffic_gb: int = Field(strict=True)
    overage_cost_toman_per_gb: int = Field(strict=True)
    target_customers: int = Field(strict=True)
    contingency_percent: int = Field(strict=True)
    target_margin_percent: int = Field(strict=True)


class ActiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


class BrandingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


def _service(request: Request) -> AdminWebService:
    service = cast("AdminWebService | None", request.app.state.admin_web_service)
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "پنل مدیریت هنوز تنظیم نشده است.")
    return service


def _same_origin(request: Request) -> None:
    expected = cast("str | None", request.app.state.admin_public_origin)
    if not expected or not hmac.compare_digest(request.headers.get("origin", ""), expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "درخواست از مبدأ مجاز نیست.")


async def _session(request: Request) -> AdminSession:
    service = _service(request)
    token = request.cookies.get(COOKIE_NAME, "")
    session = await service.session(token)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "وارد حساب مدیریت شوید.")
    return session


async def _mutating_session(
    request: Request, session: Annotated[AdminSession, Depends(_session)]
) -> AdminSession:
    _same_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "نشانهٔ امنیتی معتبر نیست.")
    return session


def _plan_data(plan: Plan) -> dict[str, object]:
    return {
        "code": plan.code, "title": plan.title, "traffic_gb": plan.traffic_gb,
        "duration_days": plan.duration_days, "price_toman": plan.price_toman,
        "is_active": plan.is_active, "sort_order": plan.sort_order, "emoji": plan.emoji,
    }


async def _pricing_data(service: AdminWebService) -> dict[str, object]:
    assumptions = await service.get_pricing()
    plans = await service.list_plans()
    if assumptions is None:
        return {"assumptions": None, "plans": [_plan_data(p) for p in plans], "projections": []}
    display = {
        "period_days": assumptions.period_days,
        "daily_server_cost_toman": assumptions.daily_server_cost_rial // 10,
        "included_traffic_gb": assumptions.included_traffic_gb,
        "overage_cost_toman_per_gb": assumptions.overage_cost_rial_per_gb // 10,
        "target_customers": assumptions.target_customers,
        "contingency_percent": assumptions.contingency_basis_points // 100,
        "target_margin_percent": assumptions.target_margin_basis_points // 100,
    }
    return {"assumptions": display, "plans": [_plan_data(p) for p in plans],
            "projections": [asdict(p) for p in await service.pricing_projections(assumptions)]}


def build_admin_web_router() -> APIRouter:
    router = APIRouter()

    @router.get("/admin", include_in_schema=False)
    @router.get("/admin/", include_in_schema=False)
    async def admin_page() -> FileResponse:
        return FileResponse(ASSETS / "index.html", media_type="text/html")

    @router.get("/admin/logo.png", include_in_schema=False)
    async def admin_logo() -> FileResponse:
        return FileResponse(LOGO, media_type="image/png")

    @router.post("/admin/api/login")
    async def login(body: LoginBody, request: Request) -> JSONResponse:
        _same_origin(request)
        try:
            result = await _service(request).login(body.username, body.password.get_secret_value())
        except AdminLoginDenied as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "نام کاربری یا رمز عبور معتبر نیست.") from exc
        response = JSONResponse(
            {"username": result.session.username, "csrf": result.session.csrf_token,
             "expires_at": result.session.expires_at.isoformat()}
        )
        response.set_cookie(
            COOKIE_NAME, result.token, max_age=12 * 60 * 60, path="/admin",
            secure=True, httponly=True, samesite="strict",
        )
        return response

    @router.get("/admin/api/me")
    async def me(session: Annotated[AdminSession, Depends(_session)]) -> dict[str, str]:
        return {"username": session.username, "csrf": session.csrf_token,
                "expires_at": session.expires_at.isoformat()}

    @router.post("/admin/api/logout")
    async def logout(
        request: Request, _: Annotated[AdminSession, Depends(_mutating_session)]
    ) -> Response:
        await _service(request).logout(request.cookies.get(COOKIE_NAME, ""))
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(COOKIE_NAME, path="/admin", secure=True, httponly=True,
                               samesite="strict")
        return response

    @router.post("/admin/api/password")
    async def change_password(
        body: PasswordBody, request: Request,
        session: Annotated[AdminSession, Depends(_mutating_session)],
    ) -> Response:
        try:
            await _service(request).change_password(
                session.username, body.current_password.get_secret_value(),
                body.new_password.get_secret_value(),
            )
        except AdminLoginDenied as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "رمز فعلی معتبر نیست.") from exc
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(COOKIE_NAME, path="/admin", secure=True, httponly=True,
                               samesite="strict")
        return response

    @router.get("/admin/api/overview")
    async def overview(
        request: Request, _: Annotated[AdminSession, Depends(_session)]
    ) -> dict[str, object]:
        service = _service(request)
        snapshot = await service.overview()
        data: dict[str, object] = asdict(snapshot)
        data["financial"] = asdict(await service.finances())
        return data

    @router.get("/admin/api/readiness")
    async def readiness(
        request: Request, _: Annotated[AdminSession, Depends(_session)]
    ) -> dict[str, bool]:
        return {
            "callback_configured": request.app.state.payment_service is not None,
            "subscription_api_configured": (
                request.app.state.access_service is not None
                and request.app.state.subscription_public_base_url is not None
            ),
            "xray_provisioning_connected": False,
            "live_usage_connected": False,
            "sales_enabled": False,
        }

    @router.get("/admin/api/users")
    async def users(
        request: Request, _: Annotated[AdminSession, Depends(_session)],
        q: str = Query(default="", max_length=64), offset: int = Query(default=0, ge=0, le=10_000),
    ) -> list[dict[str, object]]:
        rows = await _service(request).users(q.strip(), offset)
        return [asdict(row) for row in rows]

    @router.get("/admin/api/orders")
    async def orders(
        request: Request, _: Annotated[AdminSession, Depends(_session)],
        offset: int = Query(default=0, ge=0, le=10_000),
    ) -> list[dict[str, object]]:
        return [asdict(row) for row in await _service(request).orders(offset)]

    @router.get("/admin/api/payments")
    async def payments(
        request: Request, _: Annotated[AdminSession, Depends(_session)],
        offset: int = Query(default=0, ge=0, le=10_000),
    ) -> list[dict[str, object]]:
        return [asdict(row) for row in await _service(request).payments(offset)]

    @router.get("/admin/api/pricing")
    async def pricing(
        request: Request, _: Annotated[AdminSession, Depends(_session)]
    ) -> dict[str, object]:
        return await _pricing_data(_service(request))

    @router.put("/admin/api/pricing")
    async def save_pricing(
        body: PricingBody, request: Request,
        _: Annotated[AdminSession, Depends(_mutating_session)],
    ) -> dict[str, object]:
        value = PricingAssumptions(
            period_days=body.period_days,
            daily_server_cost_rial=body.daily_server_cost_toman * 10,
            included_traffic_gb=body.included_traffic_gb,
            overage_cost_rial_per_gb=body.overage_cost_toman_per_gb * 10,
            target_customers=body.target_customers,
            contingency_basis_points=body.contingency_percent * 100,
            target_margin_basis_points=body.target_margin_percent * 100,
        )
        service = _service(request)
        try:
            await service.save_pricing(value)
        except PricingValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return await _pricing_data(service)

    @router.get("/admin/api/plans")
    async def plans(
        request: Request, _: Annotated[AdminSession, Depends(_session)]
    ) -> list[dict[str, object]]:
        return [_plan_data(plan) for plan in await _service(request).list_plans()]

    @router.post("/admin/api/plans")
    async def create_plan(
        body: PlanBody, request: Request, _: Annotated[AdminSession, Depends(_mutating_session)]
    ) -> dict[str, object]:
        try:
            plan = await _service(request).save_plan(
                code=body.code, title=body.title, traffic_gb=body.traffic_gb,
                duration_days=body.duration_days, price_rial=body.price_toman * 10,
                sort_order=body.sort_order, emoji=body.emoji, editing=False,
            )
        except (PlanValidationError, UnknownPlanError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return _plan_data(plan)

    @router.put("/admin/api/plans/{code}")
    async def update_plan(
        code: str, body: PlanBody, request: Request,
        _: Annotated[AdminSession, Depends(_mutating_session)],
    ) -> dict[str, object]:
        if body.code != code:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "کد پلن قابل تغییر نیست.")
        try:
            plan = await _service(request).save_plan(
                code=code, title=body.title, traffic_gb=body.traffic_gb,
                duration_days=body.duration_days, price_rial=body.price_toman * 10,
                sort_order=body.sort_order, emoji=body.emoji, editing=True,
            )
        except (PlanValidationError, UnknownPlanError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return _plan_data(plan)

    @router.patch("/admin/api/plans/{code}/active")
    async def set_plan_active(
        code: str, body: ActiveBody, request: Request,
        _: Annotated[AdminSession, Depends(_mutating_session)],
    ) -> dict[str, object]:
        try:
            return _plan_data(await _service(request).set_plan_active(code, body.active))
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    @router.get("/admin/api/branding")
    async def branding(
        request: Request, _: Annotated[AdminSession, Depends(_session)]
    ) -> dict[str, str]:
        return asdict(await _service(request).get_branding())

    @router.patch("/admin/api/branding/{field}")
    async def update_branding(
        field: Literal["name", "short_description", "description"],
        body: BrandingBody, request: Request,
        _: Annotated[AdminSession, Depends(_mutating_session)],
    ) -> dict[str, str]:
        try:
            return asdict(await _service(request).update_branding(field, body.value))
        except BrandingValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return router
