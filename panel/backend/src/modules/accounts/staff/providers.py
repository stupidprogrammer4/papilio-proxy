from dishka import Provider, Scope, provide

from src.modules.accounts.staff.app.administration import StaffAdministration
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.roles import (
    RoleCommand,
    RoleHistoryQuery,
    RoleMemberQuery,
    RoleQuery,
    StaffRoleCommand,
    StaffRoleHistoryQuery,
)
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import (
    StaffAuthorityReader,
    StaffSessionReader,
)
from src.modules.accounts.staff.infra.roles import (
    RoleRepository,
    RoleRevisionRepository,
    StaffRoleChangeRepository,
    StaffRoleRepository,
)
from src.modules.accounts.staff.interfaces import (
    IRoleCommand,
    IRoleHistoryQuery,
    IRoleMemberQuery,
    IRoleQuery,
    IStaffAdministration,
    IStaffAuth,
    IStaffRoleCommand,
    IStaffRoleHistoryQuery,
)


class StaffProvider(Provider):
    scope = Scope.REQUEST
    passwords = provide(Passwords)
    repository = provide(StaffRepository)
    sessions = provide(StaffSessionReader)
    service = provide(StaffAuth, provides=IStaffAuth)
    authority = provide(StaffAuthorityReader)
    administration = provide(
        StaffAdministration, provides=IStaffAdministration
    )
    roles = provide(RoleRepository)
    role_revisions = provide(RoleRevisionRepository)
    role_assignments = provide(StaffRoleRepository)
    role_changes = provide(StaffRoleChangeRepository)
    role_query = provide(RoleQuery, provides=IRoleQuery)
    role_history = provide(RoleHistoryQuery, provides=IRoleHistoryQuery)
    assignment_history = provide(
        StaffRoleHistoryQuery, provides=IStaffRoleHistoryQuery
    )
    role_command = provide(RoleCommand, provides=IRoleCommand)
    assignment_command = provide(StaffRoleCommand, provides=IStaffRoleCommand)
    role_members = provide(RoleMemberQuery, provides=IRoleMemberQuery)
