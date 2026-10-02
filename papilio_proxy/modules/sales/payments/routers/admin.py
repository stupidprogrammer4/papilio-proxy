from dataclasses import asdict
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from papilio_proxy.modules.accounts.admin.domain.entities import AdminSession
from papilio_proxy.modules.accounts.admin.routers.web import _mutating_session, _session
from papilio_proxy.modules.accounts.users.domain.entities import UserBlockedError
from papilio_proxy.modules.sales.payments.app.services import PaymentService
from papilio_proxy.modules.sales.payments.domain.entities import PaymentError


class MethodBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    card_number: str = Field(min_length=16, max_length=24)
    bank_name: str = Field(min_length=1, max_length=100)
    account_holder: str = Field(min_length=1, max_length=100)
    enabled: bool = Field(strict=True)


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool = Field(strict=True)
    bank_reference: str = Field(default="", max_length=128)
    reason: str = Field(default="", max_length=300)


def _payments(request: Request) -> PaymentService:
    service = cast("PaymentService | None", request.app.state.payment_service)
    if service is None:
        raise HTTPException(503, "پرداخت‌ها در دسترس نیستند.")
    return service


def build_payment_admin_router() -> APIRouter:
    router = APIRouter(prefix="/admin/api")

    @router.get("/payment-methods")
    async def methods(
        request: Request, _: Annotated[AdminSession, Depends(_session)]
    ) -> list[dict[str, object]]:
        return [asdict(method) for method in await _payments(request).methods()]

    async def save(body: MethodBody, request: Request, method_id: str | None) -> dict[str, object]:
        try:
            method = await _payments(request).save_method(method_id=method_id, **body.model_dump())
        except PaymentError as exc:
            raise HTTPException(422, str(exc)) from exc
        return asdict(method)

    @router.post("/payment-methods")
    async def create_method(
        body: MethodBody, request: Request, _: Annotated[AdminSession, Depends(_mutating_session)]
    ) -> dict[str, object]:
        return await save(body, request, None)

    @router.put("/payment-methods/{method_id}")
    async def update_method(
        method_id: UUID,
        body: MethodBody,
        request: Request,
        _: Annotated[AdminSession, Depends(_mutating_session)],
    ) -> dict[str, object]:
        return await save(body, request, str(method_id))

    @router.get("/receipts")
    async def receipts(
        request: Request,
        _: Annotated[AdminSession, Depends(_session)],
        offset: int = Query(default=0, ge=0, le=10_000),
    ) -> list[dict[str, object]]:
        return [asdict(receipt) for receipt in await _payments(request).receipts(offset)]

    @router.get("/receipts/{receipt_id}/image")
    async def image(
        receipt_id: UUID, request: Request, _: Annotated[AdminSession, Depends(_session)]
    ) -> Response:
        try:
            image = await _payments(request).receipt_image(str(receipt_id))
        except PaymentError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(
            image,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": 'inline; filename="receipt.jpg"',
            },
        )

    @router.post("/receipts/{receipt_id}/decision")
    async def review(
        receipt_id: UUID,
        body: DecisionBody,
        request: Request,
        session: Annotated[AdminSession, Depends(_mutating_session)],
    ) -> Response:
        try:
            await _payments(request).review(
                str(receipt_id), actor=session.username, **body.model_dump()
            )
        except (PaymentError, UserBlockedError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return Response(status_code=204)

    return router


router = build_payment_admin_router()
