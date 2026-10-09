from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.network.configurations.domain.dtos import PublicProfileSearch
from src.modules.network.configurations.domain.results import (
    PublicProfile,
    PublicSubscription,
)
from src.modules.network.configurations.interfaces import (
    ISubscriptionFeedQuery,
)
from src.modules.network.configurations.routers.admin import DownloadOut

router = APIRouter(tags=["Subscriptions"], route_class=DishkaRoute)


@router.get("/s/{token}/status", include_in_schema=False)
async def detail(
    token: str, query: FromDishka[ISubscriptionFeedQuery], response: Response
) -> APIResponse[PublicSubscription, None]:
    """Read this token's subscription without administrator access."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    result = await query.detail(token)
    return APIResponse.from_data(result)


@router.get("/s/{token}/profiles", include_in_schema=False)
async def profiles(
    token: str,
    data: Annotated[PublicProfileSearch, Query()],
    query: FromDishka[ISubscriptionFeedQuery],
    response: Response,
) -> APIResponse[PublicProfile, BaseMeta]:
    """Page acknowledged profiles including WireGuard downloads."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    result = await query.profiles(token, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get(
    "/s/{token}/profiles/{profile_id:int}/download", include_in_schema=False
)
async def download_profile(
    token: str,
    profile_id: int,
    query: FromDishka[ISubscriptionFeedQuery],
    response: Response,
    host_id: int | None = Query(default=None, gt=0),
) -> APIResponse[DownloadOut, None]:
    """Download one profile owned by this subscription token."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    result = await query.profile(token, profile_id, host_id)
    return APIResponse.from_data(
        DownloadOut(
            filename=result.filename,
            content=result.content,
            media_type=result.media_type,
        )
    )


@router.get("/s/{token}", include_in_schema=False)
async def subscription(
    token: str, query: FromDishka[ISubscriptionFeedQuery]
) -> Response:
    """Refresh an active subscription's URI profiles."""
    result = await query.download(token)
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
