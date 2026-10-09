from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.operations.preferences.domain.dtos import (
    PreferencesSearch,
    PreferencesWrite,
)
from src.modules.operations.preferences.domain.models import (
    PreferencesRevisionModel,
)
from src.modules.operations.preferences.domain.results import (
    PreferencesSnapshot,
)


class IPreferencesService(Protocol):
    def current(
        self, *, locked: bool = False
    ) -> Awaitable[PreferencesSnapshot]: ...
    def write(
        self, data: PreferencesWrite, staff_id: int
    ) -> Awaitable[PreferencesSnapshot]: ...
    def history(
        self, data: PreferencesSearch
    ) -> Awaitable[ServicePage[PreferencesRevisionModel]]: ...
