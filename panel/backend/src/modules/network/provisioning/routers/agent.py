from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Query, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.network.provisioning.domain.dtos import (
    ProvisionAcknowledgement,
    ProvisioningSearch,
)
from src.modules.network.provisioning.domain.results import NodeClaim
from src.modules.network.provisioning.interfaces import (
    IProvisioningCommand,
    IProvisioningQuery,
)
from src.modules.network.provisioning.routers.admin import TaskOut

router = APIRouter(
    prefix="/v1/nodes", tags=["Node Provisioning"], route_class=DishkaRoute
)


@router.get("/{code}/provisioning")
async def page(
    code: str,
    data: Annotated[ProvisioningSearch, Query()],
    query: FromDishka[IProvisioningQuery],
    response: Response,
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[TaskOut, BaseMeta]:
    """List this node's recoverable work."""
    response.headers["Cache-Control"] = "no-store"
    result = await query.node_tasks(code, x_papilio_node_key, data)
    return APIResponse(
        success=True,
        data=[TaskOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/{code}/provisioning/{id:int}/claim")
async def claim(
    code: str,
    id: int,
    command: FromDishka[IProvisioningCommand],
    response: Response,
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[NodeClaim, None]:
    """Lease one work item; payload contains private node credentials."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.claim(code, x_papilio_node_key, id)
    return APIResponse.from_data(result)


@router.post("/{code}/provisioning/{id:int}/acknowledge")
async def acknowledge(
    code: str,
    id: int,
    data: ProvisionAcknowledgement,
    command: FromDishka[IProvisioningCommand],
    response: Response,
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[TaskOut, None]:
    """Acknowledge the same lease after apply or revoke."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.acknowledge(code, x_papilio_node_key, id, data)
    return APIResponse.from_data(TaskOut.from_model(result))
