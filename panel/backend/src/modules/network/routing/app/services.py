from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.configurations.domain.dtos import (
    RealityOptions,
    ShadowsocksOptions,
    WireguardOptions,
)
from src.modules.network.configurations.interfaces import IConfigurationCommand
from src.modules.network.routing.domain.dtos import (
    GroupWrite,
    HostWrite,
    MembershipWrite,
    RoutingSearch,
)
from src.modules.network.routing.domain.models import (
    HostGroupModel,
    HostMembershipModel,
    HostModel,
)
from src.modules.network.routing.domain.results import GroupHostFacts
from src.modules.network.routing.infra.mysql import (
    HostGroupRepository,
    HostMembershipRepository,
    HostRepository,
)
from src.modules.network.routing.infra.readers import GroupHostReader
from src.modules.network.routing.interfaces import (
    IHostGroupService,
    IHostService,
)


class HostService:
    def __init__(
        self,
        repo: HostRepository,
        configurations: IConfigurationCommand,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.configurations = configurations
        self.settings = settings

    @transactional
    async def create(
        self, configuration_id: int, data: HostWrite
    ) -> HostModel:
        await self.configurations.get(configuration_id)
        result = await self.repo.create(
            HostModel(configuration_id=configuration_id, **data.model_dump())
        )
        return result

    async def get(self, id: int) -> HostModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise missing("host", id)
        return result

    @transactional
    async def update(self, id: int, data: HostWrite) -> HostModel:
        existing = await self.get(id)
        result = await self.repo.change(
            existing, HostModel.patch(**data.model_dump())
        )
        return result

    async def search(
        self, configuration_id: int | None, data: RoutingSearch
    ) -> ServicePage[HostModel]:
        if configuration_id is not None:
            await self.configurations.get(configuration_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            configuration_id, data.q, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)


class HostGroupService:
    def __init__(
        self, repo: HostGroupRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def get(self, id: int) -> HostGroupModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise missing("host_group", id)
        return result

    @handle_conflicts
    @transactional
    async def create(self, data: GroupWrite) -> HostGroupModel:
        result = await self.repo.create(HostGroupModel(**data.model_dump()))
        return result

    @handle_conflicts
    @transactional
    async def update(self, id: int, data: GroupWrite) -> HostGroupModel:
        existing = await self.get(id)
        result = await self.repo.change(
            existing, HostGroupModel.patch(**data.model_dump())
        )
        return result

    async def search(self, data: RoutingSearch) -> ServicePage[HostGroupModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(data.q, (data.page - 1) * limit, limit)
        return service_page(result, limit)


class HostMembershipService:
    def __init__(
        self,
        repo: HostMembershipRepository,
        groups: IHostGroupService,
        hosts: IHostService,
        configurations: IConfigurationCommand,
    ) -> None:
        self.repo = repo
        self.groups = groups
        self.hosts = hosts
        self.configurations = configurations

    async def get(
        self, group_id: int, host_id: int
    ) -> HostMembershipModel | None:
        await self.groups.get(group_id)
        await self.hosts.get(host_id)
        result = await self.repo.find(group_id, host_id)
        return result

    @handle_conflicts
    @transactional
    async def put(
        self, group_id: int, host_id: int, data: MembershipWrite
    ) -> HostMembershipModel:
        await self.groups.get(group_id)
        host = await self.hosts.get(host_id)
        options = (
            await self.configurations.settings(host.configuration_id)
        ).options
        if data.server_name is not None and (
            isinstance(options, (WireguardOptions, ShadowsocksOptions))
            or isinstance(options, RealityOptions)
            and data.server_name != options.server_name
        ):
            raise ConflictException(
                message="نام سرور با تنظیمات ورودی سازگار نیست.",
                message_code="host_sni_mismatch",
                unique_dict={"host_id": host_id},
            )
        existing = await self.repo.find(group_id, host_id)
        changes = HostMembershipModel(
            group_id=group_id, host_id=host_id, **data.model_dump()
        )
        if existing is None:
            result = await self.repo.create(changes)
        else:
            result = await self.repo.change(
                existing, HostMembershipModel.patch(**data.model_dump())
            )
        return result

    @transactional
    async def remove(self, group_id: int, host_id: int) -> None:
        await self.groups.get(group_id)
        existing = await self.repo.find(group_id, host_id)
        if existing is None:
            raise missing("membership", host_id)
        await self.repo.remove_by_id(existing.id)


class GroupHostQuery:
    def __init__(
        self,
        reader: GroupHostReader,
        groups: IHostGroupService,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.groups = groups
        self.settings = settings

    async def search(
        self, group_id: int, data: RoutingSearch
    ) -> ServicePage[GroupHostFacts]:
        await self.groups.get(group_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            group_id, data.q, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)


def missing(entity: str, id: int) -> NotFoundException:
    return NotFoundException(
        message="رکورد پیدا نشد.",
        message_code=entity + "_not_found",
        entity=entity,
        identifier="id",
        identifier_value=id,
    )
