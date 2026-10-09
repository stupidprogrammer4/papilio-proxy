import json

from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.administration import (
    conflict,
    missing,
    verify_delegation,
)
from src.modules.accounts.staff.domain.dtos import StaffSearch
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.domain.results import StaffAccess
from src.modules.accounts.staff.domain.roles import (
    RoleAssignmentMode,
    RoleCreate,
    RoleHistorySearch,
    RoleModel,
    RoleRevisionModel,
    RoleSearch,
    RoleWrite,
    StaffRoleChangeModel,
    StaffRoleWrite,
)
from src.modules.accounts.staff.infra.readers import StaffAuthorityReader
from src.modules.accounts.staff.infra.roles import (
    RoleRepository,
    RoleRevisionRepository,
    StaffRoleChangeRepository,
    StaffRoleRepository,
)


class RoleQuery:
    def __init__(
        self, repo: RoleRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def search(self, data: RoleSearch) -> ServicePage[RoleModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            data.q, data.is_active, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)

    async def get(self, id: int) -> RoleModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise role_missing(id)
        return result


class RoleHistoryQuery:
    def __init__(
        self, repo: RoleRevisionRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def search(
        self, id: int, data: RoleHistorySearch
    ) -> ServicePage[RoleRevisionModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(id, (data.page - 1) * limit, limit)
        return service_page(result, limit)


class StaffRoleHistoryQuery:
    def __init__(
        self, repo: StaffRoleChangeRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def search(
        self, id: int, data: RoleHistorySearch
    ) -> ServicePage[StaffRoleChangeModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(id, (data.page - 1) * limit, limit)
        return service_page(result, limit)


class RoleCommand:
    def __init__(
        self,
        repo: RoleRepository,
        history: RoleRevisionRepository,
        authority: StaffAuthorityReader,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.history = history
        self.authority = authority
        self.settings = settings

    @handle_conflicts
    @transactional
    async def create(self, data: RoleCreate, actor_id: int) -> RoleModel:
        await self.authority.locked_owners()
        actor = await self.authority.access(actor_id, True)
        verify_delegation(actor, "create", frozenset(data.scopes))
        self.validate_capacity(data.scopes)
        role = await self.repo.create(
            RoleModel(
                code=data.code,
                title=data.title,
                is_active=data.is_active,
                scopes_json=json.dumps(data.scopes),
                revision=1,
            )
        )
        await self.history.create(
            RoleRevisionModel(
                role_id=role.id,
                revision=1,
                title=role.title,
                is_active=role.is_active,
                scopes_json=role.scopes_json,
                staff_id=actor_id,
                reason=data.reason,
            )
        )
        return role

    @handle_conflicts
    @transactional
    async def update(
        self, id: int, data: RoleWrite, actor_id: int
    ) -> RoleModel:
        await self.authority.locked_owners()
        actor = await self.authority.access(actor_id, True)
        role = await self.repo.locked(id)
        if role is None:
            raise role_missing(id)
        verify_delegation(
            actor,
            "update",
            frozenset(json.loads(role.scopes_json)) | frozenset(data.scopes),
        )
        if actor is not None and "*" not in actor.effective_scopes:
            capacity = self.settings.operations.max_staff_role_members
            members = await self.authority.role_members(id, capacity + 1)
            if len(members) > capacity:
                raise conflict("staff_role_member_capacity", id)
            for member in members:
                verify_delegation(actor, "update", member.effective_scopes)
        self.validate_capacity(data.scopes)
        if role.revision != data.expected_revision:
            raise conflict("staff_role_changed", id)
        revision = role.revision + 1
        await self.history.create(
            RoleRevisionModel(
                role_id=id,
                revision=revision,
                title=data.title,
                is_active=data.is_active,
                scopes_json=json.dumps(data.scopes),
                staff_id=actor_id,
                reason=data.reason,
            )
        )
        await self.repo.update_row_by_id(
            id,
            RoleModel.patch(
                title=data.title,
                is_active=data.is_active,
                scopes_json=json.dumps(data.scopes),
                revision=revision,
            ),
        )
        result = await self.repo.get_by_id(id)
        if result is None:
            raise role_missing(id)
        return result

    def validate_capacity(self, scopes: list[str]) -> None:
        if len(scopes) > self.settings.operations.max_staff_grants:
            raise conflict("staff_grant_capacity", len(scopes))


class StaffRoleCommand:
    def __init__(
        self,
        assignments: StaffRoleRepository,
        roles: RoleRepository,
        history: StaffRoleChangeRepository,
        authority: StaffAuthorityReader,
        settings: PapilioSettings,
    ) -> None:
        self.assignments = assignments
        self.roles = roles
        self.history = history
        self.authority = authority
        self.settings = settings

    @handle_conflicts
    @transactional
    async def update(
        self, id: int, data: StaffRoleWrite, actor_id: int
    ) -> StaffAccess:
        await self.authority.locked_owners()
        actor = await self.authority.access(actor_id, True)
        target = await self.authority.access(id, True)
        if target is None:
            raise missing(id)
        verify_delegation(actor, "update", target.effective_scopes)
        previous = {role.id for role in target.roles}
        if previous != set(data.expected_role_ids):
            raise conflict("staff_role_membership_changed", id)
        incoming = set(data.role_ids)
        if data.mode == RoleAssignmentMode.REPLACE:
            desired = incoming
        elif data.mode == RoleAssignmentMode.ADD:
            desired = previous | incoming
        else:
            desired = previous - incoming
        if len(desired) > self.settings.operations.max_staff_roles:
            raise conflict("staff_role_capacity", len(desired))
        counts = await self.authority.member_counts(sorted(desired - previous))
        if any(
            item.count >= self.settings.operations.max_staff_role_members
            for item in counts
        ):
            raise conflict("staff_role_member_capacity", id)
        selected = await self.roles.selected(sorted(desired))
        missing_ids = desired - {role.id for role in selected}
        if missing_ids:
            raise NotFoundException(
                message="نقش انتخاب‌شده پیدا نشد.",
                message_code="staff_role_not_found",
                entity="staff_role",
                identifier="ids",
                identifier_value=",".join(
                    str(value) for value in sorted(missing_ids)
                ),
            )
        for role in selected:
            verify_delegation(
                actor, "update", frozenset(json.loads(role.scopes_json))
            )
        if not self.settings.operations.staff_inactive_role_assignment and any(
            not role.is_active and role.id not in previous for role in selected
        ):
            raise conflict("staff_role_inactive", id)
        if previous == desired:
            return target
        await self.assignments.replace(id, sorted(desired))
        await self.history.create(
            StaffRoleChangeModel(
                target_staff_id=id,
                actor_staff_id=actor_id,
                previous_json=json.dumps(sorted(previous)),
                current_json=json.dumps(sorted(desired)),
                reason=data.reason,
            )
        )
        result = await self.authority.access(id)
        if result is None:
            raise missing(id)
        return result


def role_missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="نقش پیدا نشد.",
        message_code="staff_role_not_found",
        entity="staff_role",
        identifier="id",
        identifier_value=id,
    )


class RoleMemberQuery:
    def __init__(
        self, reader: StaffAuthorityReader, settings: PapilioSettings
    ) -> None:
        self.reader = reader
        self.settings = settings

    async def search(
        self, id: int, data: StaffSearch
    ) -> ServicePage[StaffModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.member_page(
            id, data.q, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
