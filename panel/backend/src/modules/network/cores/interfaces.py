from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.network.cores.domain.dtos import CoreCreate, CoreSearch
from src.modules.network.cores.domain.exports import (
    CoreExport,
    CoreExportRequest,
)
from src.modules.network.cores.domain.models import CoreModel
from src.modules.network.cores.domain.results import CoreInventoryFacts


class ICoreService(Protocol):
    def supported_protocols(self, kind: str) -> tuple[str, ...]: ...

    def create(
        self, node_id: int, data: CoreCreate
    ) -> Awaitable[CoreModel]: ...
    def default(self, node_id: int, protocol: str) -> Awaitable[CoreModel]: ...
    def get(self, id: int) -> Awaitable[CoreModel]: ...
    def search(
        self, node_id: int, data: CoreSearch
    ) -> Awaitable[ServicePage[CoreModel]]: ...


class ICoreExportQuery(Protocol):
    def export(
        self, core_id: int, data: CoreExportRequest
    ) -> Awaitable[CoreExport]: ...


class ICoreInventoryQuery(Protocol):
    def detail(self, core_id: int) -> Awaitable[CoreInventoryFacts]: ...
    def search(
        self, node_id: int, data: CoreSearch
    ) -> Awaitable[ServicePage[CoreInventoryFacts]]: ...
