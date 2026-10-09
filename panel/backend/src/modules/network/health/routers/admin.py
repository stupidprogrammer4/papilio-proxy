from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.network.health.domain.dtos import NodeHealthSearch
from src.modules.network.health.interfaces import (
    INodeHealthCommand,
    INodeHealthQuery,
)

router = APIRouter(
    prefix="/v1/admin/network/health",
    tags=["Automation"],
    route_class=DishkaRoute,
)


class NodeHealthOut(BaseModel):
    node_id: int
    code: str
    label: str
    protocol: str
    is_enabled: bool
    status: str
    sample_count: int
    successful_count: int
    average_latency_ms: int | None
    last_sample_at: datetime | None
    checked_at: datetime


class CheckOut(BaseModel):
    node_id: int
    status: str
    checked_at: datetime


@router.get("", dependencies=[scoped("network")])
async def page(
    data: Annotated[NodeHealthSearch, Query()],
    query: FromDishka[INodeHealthQuery],
) -> APIResponse[NodeHealthOut, BaseMeta]:
    """Search the latest recorded checks and their underlying records."""
    result = await query.search(data)
    return APIResponse(
        success=True,
        data=[
            NodeHealthOut(
                node_id=item.node.id,
                code=item.node.code,
                label=item.node.label,
                protocol=item.node.protocol,
                is_enabled=item.node.is_enabled,
                status=item.health.status,
                sample_count=item.health.sample_count,
                successful_count=item.health.successful_count,
                average_latency_ms=item.health.average_latency_ms,
                last_sample_at=item.health.last_sample_at.replace(tzinfo=UTC)
                if item.health.last_sample_at
                else None,
                checked_at=item.health.checked_at.replace(tzinfo=UTC),
            )
            for item in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post(
    "/{node_id:int}/check", dependencies=[scoped("network", "manage")]
)
async def check(
    node_id: int, command: FromDishka[INodeHealthCommand]
) -> APIResponse[CheckOut, None]:
    """Refresh this record's latest observation."""
    result = await command.check(node_id)
    return APIResponse.from_data(
        CheckOut(
            node_id=result.node_id,
            status=result.status,
            checked_at=result.checked_at.replace(tzinfo=UTC),
        )
    )
