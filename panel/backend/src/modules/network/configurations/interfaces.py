from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.network.configurations.domain.dtos import (
    ConfigurationCreate,
    ConfigurationSearch,
    ConfigurationUpdate,
    ProfileCreate,
    ProfileSearch,
    PublicProfileSearch,
)
from src.modules.network.configurations.domain.models import (
    ConfigurationModel,
    OpenVpnSocketModel,
    ProfileModel,
)
from src.modules.network.configurations.domain.openvpn import OpenVpnCapacity
from src.modules.network.configurations.domain.results import (
    ConfigurationDownload,
    ConfigurationServerExport,
    ProfileAppliedUpdate,
    PublicProfile,
    PublicSubscription,
    StoredSettings,
    SubscriptionURL,
)
from src.modules.network.configurations.domain.server_json import (
    ServerJsonHistorySearch,
    ServerJsonRestore,
    ServerJsonRevision,
    ServerJsonState,
    ServerJsonUpdate,
)


class IConfigurationCommand(Protocol):
    def locked_many(
        self, ids: list[int]
    ) -> Awaitable[list[ConfigurationModel]]: ...
    def server_json(self, id: int) -> Awaitable[ServerJsonState]: ...
    def update_server_json(
        self, id: int, staff_id: int, data: ServerJsonUpdate
    ) -> Awaitable[ConfigurationModel]: ...
    def json_history(
        self, id: int, data: ServerJsonHistorySearch
    ) -> Awaitable[ServicePage[ServerJsonRevision]]: ...
    def restore_server_json(
        self, id: int, revision_id: int, staff_id: int, data: ServerJsonRestore
    ) -> Awaitable[ConfigurationModel]: ...
    def openvpn_policy(self) -> OpenVpnCapacity | None: ...
    def create(
        self, data: ConfigurationCreate
    ) -> Awaitable[ConfigurationModel]: ...
    def update(
        self, id: int, data: ConfigurationUpdate
    ) -> Awaitable[ConfigurationModel]: ...
    def get(self, id: int) -> Awaitable[ConfigurationModel]: ...
    def settings(self, id: int) -> Awaitable[StoredSettings]: ...
    def search(
        self, data: ConfigurationSearch
    ) -> Awaitable[ServicePage[ConfigurationModel]]: ...
    def server_many(
        self, configuration_ids: list[int]
    ) -> Awaitable[list[ConfigurationServerExport]]: ...
    def server(self, id: int) -> Awaitable[ConfigurationDownload]: ...


class IOpenVpnSocketService(Protocol):
    def reserve(
        self, data: OpenVpnSocketModel
    ) -> Awaitable[OpenVpnSocketModel]: ...
    def change(
        self, configuration_id: int, path: str
    ) -> Awaitable[OpenVpnSocketModel]: ...
    def get(self, configuration_id: int) -> Awaitable[OpenVpnSocketModel]: ...


class IProfileCommand(Protocol):
    def assign_many(
        self, subscription_id: int, configuration_ids: list[int]
    ) -> Awaitable[list[ProfileModel]]: ...
    def assign(
        self, configuration_id: int, data: ProfileCreate
    ) -> Awaitable[ProfileModel]: ...
    def search(
        self, configuration_id: int, data: ProfileSearch
    ) -> Awaitable[ServicePage[ProfileModel]]: ...
    def client(self, id: int) -> Awaitable[ConfigurationDownload]: ...
    def subscription_url(
        self, subscription_id: int, rotate: bool
    ) -> Awaitable[str]: ...
    def subscription_urls_many(
        self, subscription_ids: list[int], rotate: bool
    ) -> Awaitable[list[SubscriptionURL]]: ...
    def mark_applied_many(
        self, updates: list[ProfileAppliedUpdate]
    ) -> Awaitable[None]: ...


class ISubscriptionFeedQuery(Protocol):
    def detail(self, token: str) -> Awaitable[PublicSubscription]: ...
    def profiles(
        self, token: str, data: PublicProfileSearch
    ) -> Awaitable[ServicePage[PublicProfile]]: ...
    def profile(
        self, token: str, profile_id: int, host_id: int | None
    ) -> Awaitable[ConfigurationDownload]: ...
    def download(self, token: str) -> Awaitable[ConfigurationDownload]: ...
