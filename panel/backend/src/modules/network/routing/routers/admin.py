from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.network.routing.domain.dtos import (
    GroupWrite,
    HostSearch,
    HostWrite,
    MembershipWrite,
    RoutingSearch,
)
from src.modules.network.routing.interfaces import (
    IGroupHostQuery,
    IHostGroupService,
    IHostMembershipService,
    IHostService,
)

router = APIRouter(
    prefix="/v1/admin/network",
    tags=["Hosts and groups"],
    route_class=DishkaRoute,
    dependencies=[scoped("network")],
)


class HostOut(BaseModel):
    id: int
    configuration_id: int
    label: str
    address: str
    port: int
    is_enabled: bool


class GroupOut(BaseModel):
    id: int
    code: str
    title: str
    is_enabled: bool


class MembershipOut(BaseModel):
    id: int
    group_id: int
    host_id: int
    label: str | None
    address: str | None
    port: int | None
    server_name: str | None
    is_enabled: bool
    sort_order: int


class GroupHostOut(BaseModel):
    host: HostOut
    membership: MembershipOut


@router.get("/hosts")
async def hosts(
    data: Annotated[HostSearch, Query()],
    service: FromDishka[IHostService],
) -> APIResponse[HostOut, BaseMeta]:
    """Search all hosts or those owned by an inbound."""
    result = await service.search(data.configuration_id, data)
    return APIResponse(
        success=True,
        data=[
            HostOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/configurations/{configuration_id:int}/hosts")
async def create_host(
    configuration_id: int, data: HostWrite, service: FromDishka[IHostService]
) -> APIResponse[HostOut, None]:
    """Create a delivery address for this inbound."""
    result = await service.create(configuration_id, data)
    return APIResponse.from_data(
        HostOut.model_validate(result, from_attributes=True)
    )


@router.get("/hosts/{id:int}")
async def host(
    id: int, service: FromDishka[IHostService]
) -> APIResponse[HostOut, None]:
    """Read the selected host."""
    result = await service.get(id)
    return APIResponse.from_data(
        HostOut.model_validate(result, from_attributes=True)
    )


@router.put("/hosts/{id:int}")
async def update_host(
    id: int, data: HostWrite, service: FromDishka[IHostService]
) -> APIResponse[HostOut, None]:
    """Edit a host without changing its inbound."""
    result = await service.update(id, data)
    return APIResponse.from_data(
        HostOut.model_validate(result, from_attributes=True)
    )


@router.get("/host-groups")
async def groups(
    data: Annotated[RoutingSearch, Query()],
    service: FromDishka[IHostGroupService],
) -> APIResponse[GroupOut, BaseMeta]:
    """Search delivery groups."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[
            GroupOut.model_validate(row, from_attributes=True)
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("/host-groups")
async def create_group(
    data: GroupWrite, service: FromDishka[IHostGroupService]
) -> APIResponse[GroupOut, None]:
    """Create a delivery group."""
    result = await service.create(data)
    return APIResponse.from_data(
        GroupOut.model_validate(result, from_attributes=True)
    )


@router.get("/host-groups/{id:int}")
async def group(
    id: int, service: FromDishka[IHostGroupService]
) -> APIResponse[GroupOut, None]:
    """Read a selected delivery group."""
    result = await service.get(id)
    return APIResponse.from_data(
        GroupOut.model_validate(result, from_attributes=True)
    )


@router.put("/host-groups/{id:int}")
async def update_group(
    id: int, data: GroupWrite, service: FromDishka[IHostGroupService]
) -> APIResponse[GroupOut, None]:
    """Edit group details and delivery availability."""
    result = await service.update(id, data)
    return APIResponse.from_data(
        GroupOut.model_validate(result, from_attributes=True)
    )


@router.get("/host-groups/{group_id:int}/hosts")
async def group_hosts(
    group_id: int,
    data: Annotated[RoutingSearch, Query()],
    service: FromDishka[IGroupHostQuery],
) -> APIResponse[GroupHostOut, BaseMeta]:
    """Search group memberships with their original hosts."""
    result = await service.search(group_id, data)
    return APIResponse(
        success=True,
        data=[
            GroupHostOut(
                host=HostOut.model_validate(row.host, from_attributes=True),
                membership=MembershipOut.model_validate(
                    row.membership, from_attributes=True
                ),
            )
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


class MembershipDetailOut(BaseModel):
    membership: MembershipOut | None


@router.get("/host-groups/{group_id:int}/hosts/{host_id:int}")
async def member_detail(
    group_id: int, host_id: int, service: FromDishka[IHostMembershipService]
) -> APIResponse[MembershipDetailOut, None]:
    """Read a host's existing overrides in this group, if assigned."""
    result = await service.get(group_id, host_id)
    return APIResponse.from_data(
        MembershipDetailOut(
            membership=None
            if result is None
            else MembershipOut.model_validate(result, from_attributes=True)
        )
    )


@router.put("/host-groups/{group_id:int}/hosts/{host_id:int}")
async def put_member(
    group_id: int,
    host_id: int,
    data: MembershipWrite,
    service: FromDishka[IHostMembershipService],
) -> APIResponse[MembershipOut, None]:
    """Assign or replace this group's overrides for a host."""
    result = await service.put(group_id, host_id, data)
    return APIResponse.from_data(
        MembershipOut.model_validate(result, from_attributes=True)
    )


@router.delete(
    "/host-groups/{group_id:int}/hosts/{host_id:int}", status_code=204
)
async def remove_member(
    group_id: int, host_id: int, service: FromDishka[IHostMembershipService]
) -> Response:
    """Remove the host from this group only."""
    await service.remove(group_id, host_id)
    return Response(status_code=204)
