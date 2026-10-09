from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Query, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.network.core_runtime.domain.dtos import (
    RuntimeAcknowledgement,
    RuntimeClaim,
    RuntimeSearch,
)
from src.modules.network.core_runtime.domain.results import (
    RuntimeCommandOut,
    RuntimeUsageObservationOut,
)
from src.modules.network.core_runtime.domain.usage import (
    RuntimeUsageObservation,
)
from src.modules.network.core_runtime.interfaces import (
    ICoreRuntimeCommand,
    ICoreRuntimeQuery,
    ICoreUsageObservationCommand,
)

router = APIRouter(
    prefix="/v1/nodes", tags=["Node core runtime"], route_class=DishkaRoute
)


@router.post("/{code}/usage-observations/{core_id:int}")
async def observe_usage(
    code: str,
    core_id: int,
    data: RuntimeUsageObservation,
    command: FromDishka[ICoreUsageObservationCommand],
    response: Response,
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[RuntimeUsageObservationOut, None]:
    response.headers["Cache-Control"] = "no-store"
    result = await command.observe(code, x_papilio_node_key, core_id, data)
    return APIResponse.from_data(result)


@router.get("/{code}/runtime-commands")
async def page(
    code: str,
    data: Annotated[RuntimeSearch, Query()],
    query: FromDishka[ICoreRuntimeQuery],
    response: Response,
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[RuntimeCommandOut, BaseMeta]:
    """List this node's lifecycle commands."""
    response.headers["Cache-Control"] = "no-store"
    result = await query.node_commands(code, x_papilio_node_key, data)
    return APIResponse(
        success=True,
        data=[
            RuntimeCommandOut.model_validate(row.model_dump())
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/{code}/runtime-commands/{id:int}/claim")
async def claim(
    code: str,
    id: int,
    command: FromDishka[ICoreRuntimeCommand],
    response: Response,
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[RuntimeClaim, None]:
    """Lease a private bundle; credentials must stay on the node."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.claim(code, x_papilio_node_key, id)
    return APIResponse.from_data(result)


@router.post("/{code}/runtime-commands/{id:int}/acknowledge")
async def acknowledge(
    code: str,
    id: int,
    data: RuntimeAcknowledgement,
    command: FromDishka[ICoreRuntimeCommand],
    response: Response,
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[RuntimeCommandOut, None]:
    """Commit the exact lease result without provisioning claims."""
    response.headers["Cache-Control"] = "no-store"
    result = await command.acknowledge(code, x_papilio_node_key, id, data)
    return APIResponse.from_data(
        RuntimeCommandOut.model_validate(result.model_dump())
    )
