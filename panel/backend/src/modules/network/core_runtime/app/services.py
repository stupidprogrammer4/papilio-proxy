from datetime import UTC, datetime

from papilio.errors.exceptions import NotFoundException

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.domain.dtos import RuntimeSearch
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeCommandModel,
    CoreRuntimeRevisionModel,
    CoreRuntimeStateModel,
)
from src.modules.network.core_runtime.infra.mysql import (
    RuntimeCommandRepository,
    RuntimeRevisionRepository,
    RuntimeStateRepository,
)


def missing(entity: str, id: int) -> NotFoundException:
    return NotFoundException(
        message="Runtime record not found.",
        message_code="runtime_record_not_found",
        entity=entity,
        identifier="id",
        identifier_value=id,
    )


class RuntimeStateService:
    def __init__(
        self, repo: RuntimeStateRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    async def lock_core(self, core_id: int) -> None:
        policy = self.settings.core_usage
        if policy is not None and policy.mode != "disabled":
            await self.repo.lock_node_for_core(core_id)
        await self.repo.lock_core(core_id)

    async def lock_cores(self, core_ids: list[int]) -> None:
        policy = self.settings.core_usage
        if policy is not None and policy.mode != "disabled":
            await self.repo.lock_nodes_for_cores(core_ids)
        await self.repo.lock_cores(core_ids)

    async def current(self, core_id: int) -> CoreRuntimeStateModel | None:
        result = await self.repo.for_core(core_id, lock=True)
        return result

    async def find(self, core_id: int) -> CoreRuntimeStateModel | None:
        result = await self.repo.for_core(core_id)
        return result

    async def locked(self, core_id: int) -> CoreRuntimeStateModel:
        await self.lock_core(core_id)
        row = await self.repo.for_core(core_id, lock=True)
        if row is None:
            row = await self.repo.create(
                CoreRuntimeStateModel(core_id=core_id)
            )
        return row

    async def change(
        self, row: CoreRuntimeStateModel, patch: CoreRuntimeStateModel
    ) -> CoreRuntimeStateModel:
        result = await self.repo.change(row, patch)
        return result


class RuntimeRevisionService:
    def __init__(self, repo: RuntimeRevisionRepository) -> None:
        self.repo = repo

    async def create(
        self, row: CoreRuntimeRevisionModel
    ) -> CoreRuntimeRevisionModel:
        result = await self.repo.create(row)
        return result

    async def get(self, id: int, core_id: int) -> CoreRuntimeRevisionModel:
        row = await self.repo.current(id, core_id)
        if row is None:
            raise missing("runtime_revision", id)
        return row


class RuntimeCommandService:
    def __init__(
        self, repo: RuntimeCommandRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def create(
        self, row: CoreRuntimeCommandModel
    ) -> CoreRuntimeCommandModel:
        result = await self.repo.create(row)
        return result

    async def get(self, id: int) -> CoreRuntimeCommandModel:
        row = await self.repo.current(id)
        if row is None:
            raise missing("runtime_command", id)
        return row

    async def locked_get(self, id: int) -> CoreRuntimeCommandModel:
        row = await self.repo.current(id, lock=True)
        if row is None:
            raise missing("runtime_command", id)
        return row

    async def by_key(
        self, core_id: int, key: str
    ) -> CoreRuntimeCommandModel | None:
        result = await self.repo.by_key(core_id, key)
        return result

    async def outstanding(
        self, core_id: int
    ) -> CoreRuntimeCommandModel | None:
        result = await self.repo.outstanding(core_id, ["queued", "leased"])
        return result

    async def change(
        self, row: CoreRuntimeCommandModel, patch: CoreRuntimeCommandModel
    ) -> CoreRuntimeCommandModel:
        result = await self.repo.change(row, patch)
        return result

    async def actionable(
        self, node_id: int, data: RuntimeSearch
    ) -> ServicePage[CoreRuntimeCommandModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.actionable_page(
            node_id,
            ["queued", "leased"],
            datetime.now(UTC).replace(tzinfo=None),
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)

    async def search(
        self, core_id: int | None, node_id: int | None, data: RuntimeSearch
    ) -> ServicePage[CoreRuntimeCommandModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            core_id, node_id, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
