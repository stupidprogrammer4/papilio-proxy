from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.network.nodes.domain.dtos import (
    NodeCreate,
    NodeEnabled,
    NodeSearch,
    QualitySearch,
)
from src.modules.network.nodes.domain.models import NodeModel
from src.modules.network.nodes.interfaces import (
    INodeQualityQuery,
    INodeService,
)

router = APIRouter(
    prefix="/v1/admin/network",
    tags=["Admin Network"],
    route_class=DishkaRoute,
    dependencies=[scoped("network")],
)


class NodeOut(BaseModel):
    id: int
    code: str
    label: str
    public_host: str
    public_port: int
    protocol: str
    is_enabled: bool

    @classmethod
    def from_model(cls, item: NodeModel) -> "NodeOut":
        return cls.model_validate(item, from_attributes=True)


class RegisteredNodeOut(BaseModel):
    node: NodeOut
    agent_key: str


class NodeQualityOut(BaseModel):
    node_id: int
    code: str
    label: str
    protocol: str
    client_network: str
    sample_count: int
    successful_count: int
    average_latency_ms: int | None
    score: float | None


@router.get("/nodes")
async def page(
    data: Annotated[NodeSearch, Query()], service: FromDishka[INodeService]
) -> APIResponse[NodeOut, BaseMeta]:
    """List configured proxy endpoints."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[NodeOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/nodes")
async def register(
    data: NodeCreate, service: FromDishka[INodeService]
) -> APIResponse[RegisteredNodeOut, None]:
    """Register a disabled endpoint and reveal its agent key once."""
    result = await service.register(data)
    return APIResponse.from_data(
        RegisteredNodeOut(
            node=NodeOut.from_model(result.node), agent_key=result.agent_key
        )
    )


@router.patch("/nodes/{id:int}/enabled")
async def enabled(
    id: int, data: NodeEnabled, service: FromDishka[INodeService]
) -> APIResponse[NodeOut, None]:
    """Set endpoint availability after owner review."""
    result = await service.set_enabled(id, data)
    return APIResponse.from_data(NodeOut.from_model(result))


@router.get("/quality")
async def quality(
    data: Annotated[QualitySearch, Query()],
    reader: FromDishka[INodeQualityQuery],
) -> APIResponse[NodeQualityOut, None]:
    """Rank endpoints using recent probes from one named client network."""
    result = await reader.ranked(data.client_network)
    return APIResponse(
        success=True,
        data=[
            NodeQualityOut.model_validate(item, from_attributes=True)
            for item in result
        ],
    )


@router.get("/nodes/{id:int}")
async def detail(
    id: int, service: FromDishka[INodeService]
) -> APIResponse[NodeOut, None]:
    """Read one registered node."""
    result = await service.get(id)
    return APIResponse.from_data(NodeOut.from_model(result))
