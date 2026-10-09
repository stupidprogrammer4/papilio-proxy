from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.accounts.staff.domain.dtos import (
    StaffAccessWrite,
    StaffCreate,
    StaffPasswordWrite,
    StaffSearch,
)
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.domain.results import (
    IssuedSession,
    Principal,
    StaffAccess,
)
from src.modules.accounts.staff.domain.roles import (
    RoleCreate,
    RoleHistorySearch,
    RoleModel,
    RoleRevisionModel,
    RoleSearch,
    RoleWrite,
    StaffRoleChangeModel,
    StaffRoleWrite,
)


class IStaffAuth(Protocol):
    def login(
        self, username: str, password: str
    ) -> Awaitable[IssuedSession]: ...
    def current(self, token: str) -> Awaitable[Principal]: ...
    def logout(self, token: str) -> Awaitable[None]: ...
    def create_owner(
        self, username: str, password: str
    ) -> Awaitable[None]: ...


class IStaffAdministration(Protocol):
    def search(
        self, data: StaffSearch
    ) -> Awaitable[ServicePage[StaffModel]]: ...
    def get(self, id: int) -> Awaitable[StaffAccess]: ...
    def create(
        self, data: StaffCreate, actor_id: int
    ) -> Awaitable[StaffAccess]: ...
    def update_access(
        self, id: int, data: StaffAccessWrite, actor_id: int
    ) -> Awaitable[StaffAccess]: ...
    def reset_password(
        self, id: int, data: StaffPasswordWrite, actor_id: int
    ) -> Awaitable[None]: ...


class IRoleQuery(Protocol):
    def search(
        self, data: RoleSearch
    ) -> Awaitable[ServicePage[RoleModel]]: ...
    def get(self, id: int) -> Awaitable[RoleModel]: ...


class IRoleHistoryQuery(Protocol):
    def search(
        self, id: int, data: RoleHistorySearch
    ) -> Awaitable[ServicePage[RoleRevisionModel]]: ...


class IStaffRoleHistoryQuery(Protocol):
    def search(
        self, id: int, data: RoleHistorySearch
    ) -> Awaitable[ServicePage[StaffRoleChangeModel]]: ...


class IRoleCommand(Protocol):
    def create(
        self, data: RoleCreate, actor_id: int
    ) -> Awaitable[RoleModel]: ...
    def update(
        self, id: int, data: RoleWrite, actor_id: int
    ) -> Awaitable[RoleModel]: ...


class IStaffRoleCommand(Protocol):
    def update(
        self, id: int, data: StaffRoleWrite, actor_id: int
    ) -> Awaitable[StaffAccess]: ...


class IRoleMemberQuery(Protocol):
    def search(
        self, id: int, data: StaffSearch
    ) -> Awaitable[ServicePage[StaffModel]]: ...
