from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.network.cores.domain.dtos import CoreCreate, CoreSearch
from src.modules.network.cores.domain.exports import (
    CoreExport,
    CoreExportRequest,
)
from src.modules.network.cores.domain.models import CoreModel
from src.modules.network.cores.domain.results import (
    CoreInventoryFacts,
    CoreRuntimeSummary,
)
from src.modules.network.cores.interfaces import (
    ICoreExportQuery,
    ICoreInventoryQuery,
    ICoreService,
)

router = APIRouter(
    prefix="/v1/admin/network",
    tags=["Core inventory"],
    route_class=DishkaRoute,
    dependencies=[scoped("network")],
)


class CoreOut(BaseModel):
    id: int
    node_id: int
    code: str
    label: str
    kind: str
    supported_protocols: tuple[str, ...]
    application_status: str = "draft"
    runtime: CoreRuntimeSummary | None = None

    @classmethod
    def from_record(cls, row: CoreModel, service: ICoreService) -> "CoreOut":
        return cls(
            id=row.id,
            node_id=row.node_id,
            code=row.code,
            label=row.label,
            kind=row.kind,
            supported_protocols=service.supported_protocols(row.kind),
        )

    @classmethod
    def from_facts(
        cls, facts: CoreInventoryFacts, service: ICoreService
    ) -> "CoreOut":
        result = cls.from_record(facts.core, service)
        if facts.runtime is not None:
            result.runtime = CoreRuntimeSummary.model_validate(
                facts.runtime.model_dump()
            )
            if facts.runtime.applied_revision_id is not None:
                result.application_status = "applied"
        return result


@router.get("/nodes/{node_id:int}/cores")
async def page(
    node_id: int,
    data: Annotated[CoreSearch, Query()],
    service: FromDishka[ICoreService],
    query: FromDishka[ICoreInventoryQuery],
) -> APIResponse[CoreOut, BaseMeta]:
    """Search the core inventory of a node."""
    result = await query.search(node_id, data)
    return APIResponse(
        success=True,
        data=[CoreOut.from_facts(row, service) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/nodes/{node_id:int}/cores")
async def create(
    node_id: int, data: CoreCreate, service: FromDishka[ICoreService]
) -> APIResponse[CoreOut, None]:
    """Register a core draft; no process is started."""
    result = await service.create(node_id, data)
    return APIResponse.from_data(CoreOut.from_record(result, service))


@router.get("/cores/{id:int}")
async def detail(
    id: int,
    service: FromDishka[ICoreService],
    query: FromDishka[ICoreInventoryQuery],
) -> APIResponse[CoreOut, None]:
    """Read one core and its parent node."""
    result = await query.detail(id)
    return APIResponse.from_data(CoreOut.from_facts(result, service))


@router.post(
    "/cores/{id:int}/export", dependencies=[scoped("network", "manage")]
)
async def export(
    id: int,
    data: CoreExportRequest,
    response: Response,
    service: FromDishka[ICoreExportQuery],
) -> APIResponse[CoreExport, None]:
    """Export every configuration; no core is started."""
    response.headers["Cache-Control"] = "no-store"
    result = await service.export(id, data)
    return APIResponse.from_data(result)
