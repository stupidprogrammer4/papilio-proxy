from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel

from src.modules.accounts.staff.config.dependencies import CurrentStaff, scoped
from src.modules.network.configurations.domain.dtos import (
    ConfigurationCreate,
    ConfigurationOptions,
    ConfigurationSearch,
    ConfigurationServerExportRequest,
    ConfigurationUpdate,
    ProfileCreate,
    ProfileSearch,
)
from src.modules.network.configurations.domain.models import (
    ConfigurationModel,
    ProfileModel,
)
from src.modules.network.configurations.domain.openvpn import OpenVpnCapacity
from src.modules.network.configurations.domain.server_json import (
    ServerJsonHistorySearch,
    ServerJsonRestore,
    ServerJsonRevision,
    ServerJsonState,
    ServerJsonUpdate,
)
from src.modules.network.configurations.interfaces import (
    IConfigurationCommand,
    IProfileCommand,
)

router = APIRouter(
    prefix="/v1/admin/network/configurations",
    tags=["Configurations"],
    route_class=DishkaRoute,
)


class ConfigurationOut(BaseModel):
    revision: int
    id: int
    node_id: int
    core_id: int
    listen_port: int
    port_network: str
    label: str
    protocol: str
    application_status: str = "draft"

    @classmethod
    def from_model(cls, row: ConfigurationModel) -> "ConfigurationOut":
        return cls.model_validate(row, from_attributes=True)


class ConfigurationDetailOut(ConfigurationOut):
    options: ConfigurationOptions


class ProfileOut(BaseModel):
    id: int
    configuration_id: int
    subscription_id: int
    client_address: str | None

    @classmethod
    def from_model(cls, row: ProfileModel) -> "ProfileOut":
        return cls.model_validate(row, from_attributes=True)


class DownloadOut(BaseModel):
    filename: str
    content: str
    media_type: str


class SubscriptionUrlOut(BaseModel):
    url: str


@router.get("/openvpn-policy", dependencies=[scoped("network", "read")])
async def openvpn_policy(
    service: FromDishka[IConfigurationCommand],
) -> APIResponse[OpenVpnCapacity | None, None]:
    """Read operational OpenVPN draft limits without starting a core."""
    result = service.openvpn_policy()
    return APIResponse.from_data(result)


@router.get("", dependencies=[scoped("network")])
async def page(
    data: Annotated[ConfigurationSearch, Query()],
    service: FromDishka[IConfigurationCommand],
) -> APIResponse[ConfigurationOut, BaseMeta]:
    """List configuration drafts without credentials."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[ConfigurationOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post("", dependencies=[scoped("network")])
async def create(
    data: ConfigurationCreate, service: FromDishka[IConfigurationCommand]
) -> APIResponse[ConfigurationOut, None]:
    """Create encrypted node settings without starting a core."""
    result = await service.create(data)
    return APIResponse.from_data(ConfigurationOut.from_model(result))


@router.post(
    "/{id:int}/server-download", dependencies=[scoped("network", "manage")]
)
async def server_download(
    id: int, service: FromDishka[IConfigurationCommand]
) -> APIResponse[DownloadOut, None]:
    """Export server configuration with eligible clients."""
    result = await service.server(id)
    return APIResponse.from_data(
        DownloadOut.model_validate(result, from_attributes=True)
    )


class ConfigurationServerDownloadOut(DownloadOut):
    configuration_id: int
    revision: int


@router.post("/server-downloads", dependencies=[scoped("network", "manage")])
async def server_downloads(
    data: ConfigurationServerExportRequest,
    response: Response,
    service: FromDishka[IConfigurationCommand],
) -> APIResponse[ConfigurationServerDownloadOut, None]:
    """Export an explicit selection with independent batch reads."""
    response.headers["Cache-Control"] = "no-store"
    result = await service.server_many(data.configuration_ids)
    return APIResponse(
        success=True,
        data=[
            ConfigurationServerDownloadOut(
                configuration_id=row.configuration_id,
                revision=row.revision,
                filename=row.download.filename,
                media_type=row.download.media_type,
                content=row.download.content,
            )
            for row in result
        ],
    )


@router.get("/{id:int}/profiles", dependencies=[scoped("network")])
async def profiles(
    id: int,
    data: Annotated[ProfileSearch, Query()],
    command: FromDishka[IProfileCommand],
) -> APIResponse[ProfileOut, BaseMeta]:
    """List assigned profiles without credentials."""
    result = await command.search(id, data)
    return APIResponse(
        success=True,
        data=[ProfileOut.from_model(row) for row in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post(
    "/{id:int}/profiles",
    dependencies=[scoped("network"), scoped("subscriptions", "update")],
)
async def assign(
    id: int, data: ProfileCreate, command: FromDishka[IProfileCommand]
) -> APIResponse[ProfileOut, None]:
    """Prepare a paid profile, preserving credentials on retries."""
    result = await command.assign(id, data)
    return APIResponse.from_data(ProfileOut.from_model(result))


@router.post(
    "/profiles/{id:int}/client-download",
    dependencies=[scoped("network", "manage")],
)
async def client_download(
    id: int, command: FromDishka[IProfileCommand]
) -> APIResponse[DownloadOut, None]:
    """Download a private client configuration."""
    result = await command.client(id)
    return APIResponse.from_data(
        DownloadOut.model_validate(result, from_attributes=True)
    )


@router.post(
    "/subscriptions/{id:int}/link",
    dependencies=[
        scoped("network", "manage"),
        scoped("subscriptions", "update"),
    ],
)
async def subscription_link(
    id: int, command: FromDishka[IProfileCommand]
) -> APIResponse[SubscriptionUrlOut, None]:
    """Read or create the stable subscription URL."""
    result = await command.subscription_url(id, False)
    return APIResponse.from_data(SubscriptionUrlOut(url=result))


@router.post(
    "/subscriptions/{id:int}/rotate-link",
    dependencies=[
        scoped("network", "manage"),
        scoped("subscriptions", "update"),
    ],
)
async def rotate_link(
    id: int, command: FromDishka[IProfileCommand]
) -> APIResponse[SubscriptionUrlOut, None]:
    """Rotate the subscription token and invalidate the old URL."""
    result = await command.subscription_url(id, True)
    return APIResponse.from_data(SubscriptionUrlOut(url=result))


@router.get("/{id:int}", dependencies=[scoped("network")])
async def detail(
    id: int, service: FromDishka[IConfigurationCommand]
) -> APIResponse[ConfigurationDetailOut, None]:
    """Read editable options without keys or passwords."""
    row = await service.get(id)
    settings = await service.settings(id)
    return APIResponse.from_data(
        ConfigurationDetailOut(
            revision=row.revision,
            id=row.id,
            node_id=row.node_id,
            core_id=row.core_id,
            listen_port=row.listen_port,
            port_network=row.port_network,
            label=row.label,
            protocol=row.protocol,
            options=settings.options,
        )
    )


@router.put("/{id:int}", dependencies=[scoped("network")])
async def update(
    id: int,
    data: ConfigurationUpdate,
    service: FromDishka[IConfigurationCommand],
) -> APIResponse[ConfigurationOut, None]:
    """Update draft options while preserving existing credentials."""
    result = await service.update(id, data)
    return APIResponse.from_data(ConfigurationOut.from_model(result))


@router.get(
    "/{id:int}/server-json", dependencies=[scoped("network", "manage")]
)
async def server_json(
    id: int, service: FromDishka[IConfigurationCommand]
) -> APIResponse[ServerJsonState, None]:
    result = await service.server_json(id)
    return APIResponse.from_data(result)


@router.put(
    "/{id:int}/server-json",
    dependencies=[scoped("network", "manage"), scoped("network", "update")],
)
async def update_server_json(
    id: int,
    data: ServerJsonUpdate,
    principal: CurrentStaff,
    service: FromDishka[IConfigurationCommand],
) -> APIResponse[ConfigurationOut, None]:
    result = await service.update_server_json(id, principal.staff_id, data)
    return APIResponse.from_data(ConfigurationOut.from_model(result))


@router.get(
    "/{id:int}/server-json/history", dependencies=[scoped("network", "manage")]
)
async def json_history(
    id: int,
    data: Annotated[ServerJsonHistorySearch, Query()],
    service: FromDishka[IConfigurationCommand],
) -> APIResponse[ServerJsonRevision, BaseMeta]:
    result = await service.json_history(id, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.post(
    "/{id:int}/server-json/history/{revision_id:int}/restore",
    dependencies=[scoped("network", "manage"), scoped("network", "update")],
)
async def restore_server_json(
    id: int,
    revision_id: int,
    data: ServerJsonRestore,
    principal: CurrentStaff,
    service: FromDishka[IConfigurationCommand],
) -> APIResponse[ConfigurationOut, None]:
    result = await service.restore_server_json(
        id, revision_id, principal.staff_id, data
    )
    return APIResponse.from_data(ConfigurationOut.from_model(result))
