from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Query, Response, UploadFile
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.config.settings import PapilioSettings
from src.modules.accounts.customer_portal.domain.dtos import CustomerPage
from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.accounts.staff.domain.results import Principal
from src.modules.billing.receipts.app.annotation_interfaces import (
    IReceiptAnnotationCommand,
)
from src.modules.billing.receipts.domain.annotations import (
    ReceiptAnnotation,
    ReceiptAnnotationWrite,
)
from src.modules.billing.receipts.domain.results import ReceiptDetails
from src.modules.billing.receipts.interfaces import IPaymentReceiptCommand

router = APIRouter(
    prefix="/v1/admin/payments/topups",
    tags=["Payment Receipts"],
    route_class=DishkaRoute,
    dependencies=[scoped("payments")],
)


@router.post(
    "/{topup_id:int}/receipts", openapi_extra={"body_budget": "receipt"}
)
async def upload(
    topup_id: int,
    file: UploadFile,
    command: FromDishka[IPaymentReceiptCommand],
    settings: FromDishka[PapilioSettings],
) -> APIResponse[ReceiptDetails, None]:
    """Attach a private image; this does not confirm settlement."""
    content = await file.read(settings.receipts.max_image_bytes + 1)
    if len(content) > settings.receipts.max_image_bytes:
        raise HTTPException(413, "حجم رسید بیشتر از حد مجاز است.")
    result = await command.upload(topup_id, None, content)
    return APIResponse.from_data(result)


@router.get("/{topup_id:int}/receipts")
async def receipts(
    topup_id: int,
    data: Annotated[CustomerPage, Query()],
    command: FromDishka[IPaymentReceiptCommand],
) -> APIResponse[ReceiptDetails, BaseMeta]:
    """Read paginated metadata without loading encrypted images."""
    result = await command.search(topup_id, None, data.page, data.per_page)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{topup_id:int}/receipts/{id:int}")
async def download(
    topup_id: int, id: int, command: FromDishka[IPaymentReceiptCommand]
) -> Response:
    """Download an authorized receipt; never serve it as a public asset."""
    result = await command.download(topup_id, id, None)
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="receipt-{id}.jpg"',
        },
    )


@router.get("/{topup_id:int}/receipts/{id:int}/annotations")
async def annotation_history(
    topup_id: int,
    id: int,
    principal: Annotated[Principal, scoped("payments", "read")],
    data: Annotated[CustomerPage, Query()],
    command: FromDishka[IReceiptAnnotationCommand],
) -> APIResponse[ReceiptAnnotation, BaseMeta]:
    """Read the paginated operator correction history for a receipt."""
    result = await command.history(
        topup_id, id, principal, data.page, data.per_page
    )
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.put("/{topup_id:int}/receipts/{id:int}/annotations")
async def correct_annotation(
    topup_id: int,
    id: int,
    data: ReceiptAnnotationWrite,
    principal: Annotated[Principal, scoped("payments", "update")],
    command: FromDishka[IReceiptAnnotationCommand],
) -> APIResponse[ReceiptAnnotation, None]:
    """Record an audited correction without changing the OCR result."""
    result = await command.append(topup_id, id, principal, data)
    return APIResponse.from_data(result)
