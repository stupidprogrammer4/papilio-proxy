from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import CurrentStaff, scoped
from src.modules.network.core_runtime.domain.dtos import (
    RuntimeCommandCreate,
    RuntimeRevisionCreate,
    RuntimeSearch,
)
from src.modules.network.core_runtime.domain.results import (
    RuntimeCommandOut,
    RuntimeRevisionOut,
    RuntimeStateOut,
)
from src.modules.network.core_runtime.interfaces import (
    ICoreRuntimeCommand,
    ICoreRuntimeQuery,
)

router = APIRouter(
    prefix="/v1/admin/network/cores",
    tags=["Core runtime"],
    route_class=DishkaRoute,
    dependencies=[scoped("network")],
)


@router.get("/{id:int}/runtime")
async def state(
    id: int, query: FromDishka[ICoreRuntimeQuery]
) -> APIResponse[RuntimeStateOut, None]:
    """Read desired and acknowledged runtime state."""
    result = await query.state(id)
    return APIResponse.from_data(result)


@router.get("/{id:int}/runtime/revisions")
async def revisions(
    id: int,
    data: Annotated[RuntimeSearch, Query()],
    query: FromDishka[ICoreRuntimeQuery],
) -> APIResponse[RuntimeRevisionOut, BaseMeta]:
    """Browse immutable revision metadata without credentials."""
    result = await query.revisions(id, data)
    return APIResponse(
        success=True,
        data=[
            RuntimeRevisionOut.model_validate(row.model_dump())
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post(
    "/{id:int}/runtime/revisions", dependencies=[scoped("network", "manage")]
)
async def capture(
    id: int,
    data: RuntimeRevisionCreate,
    principal: CurrentStaff,
    command: FromDishka[ICoreRuntimeCommand],
) -> APIResponse[RuntimeRevisionOut, None]:
    """Capture an encrypted immutable node bundle."""
    result = await command.revision(id, data, staff_id=principal.staff_id)
    return APIResponse.from_data(
        RuntimeRevisionOut.model_validate(result.model_dump())
    )


@router.get("/{id:int}/runtime/commands")
async def commands(
    id: int,
    data: Annotated[RuntimeSearch, Query()],
    query: FromDishka[ICoreRuntimeQuery],
) -> APIResponse[RuntimeCommandOut, BaseMeta]:
    """Browse lifecycle command history."""
    result = await query.commands(id, data)
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


@router.post(
    "/{id:int}/runtime/commands", dependencies=[scoped("network", "manage")]
)
async def enqueue(
    id: int,
    data: RuntimeCommandCreate,
    principal: CurrentStaff,
    command: FromDishka[ICoreRuntimeCommand],
) -> APIResponse[RuntimeCommandOut, None]:
    """Queue a fenced lifecycle command for its enrolled node."""
    result = await command.enqueue(id, data, staff_id=principal.staff_id)
    return APIResponse.from_data(
        RuntimeCommandOut.model_validate(result.model_dump())
    )
