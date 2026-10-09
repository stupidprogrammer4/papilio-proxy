from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response

from src.modules.network.qr_codes.interfaces import ISubscriptionQrQuery

router = APIRouter(tags=["Private QR codes"], route_class=DishkaRoute)


@router.get("/s/{token}/qr", include_in_schema=False)
async def feed(
    token: str, query: FromDishka[ISubscriptionQrQuery]
) -> Response:
    """Render the current ready feed link under this private token."""
    result = await query.feed(token)
    return Response(
        content=result.content,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )


@router.get("/s/{token}/profiles/{profile_id:int}/qr", include_in_schema=False)
async def profile(
    token: str,
    profile_id: int,
    query: FromDishka[ISubscriptionQrQuery],
    host_id: int | None = Query(default=None, gt=0),
) -> Response:
    """Render an acknowledged owned profile and its selected host."""
    result = await query.profile(token, profile_id, host_id)
    return Response(
        content=result.content,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )
