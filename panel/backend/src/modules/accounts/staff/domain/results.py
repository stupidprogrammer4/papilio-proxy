import json
from dataclasses import dataclass
from datetime import datetime

from src.modules.accounts.staff.domain.models import (
    StaffModel,
    StaffSessionModel,
)
from src.modules.accounts.staff.domain.roles import RoleModel


@dataclass(frozen=True, slots=True)
class Principal:
    staff_id: int
    username: str
    scopes: frozenset[str]
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedSession:
    token: str
    principal: Principal


@dataclass(frozen=True, slots=True)
class StoredStaffSession:
    staff: StaffModel
    session: StaffSessionModel


@dataclass(frozen=True, slots=True)
class StaffAccess:
    staff: StaffModel
    scopes: frozenset[str]
    roles: tuple[RoleModel, ...] = ()

    @property
    def effective_scopes(self) -> frozenset[str]:
        return self.scopes | frozenset(
            scope
            for role in self.roles
            if role.is_active
            for scope in json.loads(role.scopes_json)
        )


@dataclass(frozen=True, slots=True)
class RoleMemberCount:
    role_id: int
    count: int
