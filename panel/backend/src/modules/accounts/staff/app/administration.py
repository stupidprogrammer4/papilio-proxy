from papilio.errors.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.domain.dtos import (
    StaffAccessWrite,
    StaffCreate,
    StaffPasswordWrite,
    StaffSearch,
)
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.domain.results import StaffAccess
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffAuthorityReader


class StaffAdministration:
    def __init__(
        self,
        repo: StaffRepository,
        authority: StaffAuthorityReader,
        passwords: Passwords,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.authority = authority
        self.passwords = passwords
        self.settings = settings

    async def search(self, data: StaffSearch) -> ServicePage[StaffModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(data.q, (data.page - 1) * limit, limit)
        return service_page(result, limit)

    async def get(self, id: int) -> StaffAccess:
        result = await self.authority.access(id)
        if result is None:
            raise missing(id)
        return result

    @handle_conflicts
    @transactional
    async def create(self, data: StaffCreate, actor_id: int) -> StaffAccess:
        await self.authority.locked_owners()
        actor = await self.authority.access(actor_id, True)
        verify_delegation(actor, "create", frozenset(data.scopes))
        self.validate_capacity(data.scopes)
        hashed = await self.passwords.hash(data.password.get_secret_value())
        staff = await self.repo.create(
            StaffModel(
                username=data.username,
                password_hash=hashed,
                is_active=data.is_active,
            )
        )
        await self.repo.replace_grants(staff.id, data.scopes)
        return StaffAccess(staff, frozenset(data.scopes))

    @handle_conflicts
    @transactional
    async def update_access(
        self, id: int, data: StaffAccessWrite, actor_id: int
    ) -> StaffAccess:
        owners = await self.authority.locked_owners()
        actor = await self.authority.access(actor_id, True)
        target = await self.authority.access(id, True)
        if target is None:
            raise missing(id)
        verify_delegation(
            actor, "update", target.effective_scopes | frozenset(data.scopes)
        )
        self.validate_capacity(data.scopes)
        if (
            target.staff.is_active != data.expected_is_active
            or target.scopes != frozenset(data.expected_scopes)
        ):
            raise conflict("staff_access_changed", id)
        if (
            target.staff.is_active
            and "*" in target.scopes
            and (not data.is_active or "*" not in data.scopes)
            and not any(owner.id != id and owner.is_active for owner in owners)
        ):
            raise conflict("staff_last_owner", id)
        await self.repo.update_row_by_id(
            id, StaffModel.patch(is_active=data.is_active)
        )
        await self.repo.replace_grants(id, data.scopes)
        if not data.is_active:
            await self.repo.revoke_sessions(id)
        result = await self.get(id)
        return result

    @handle_conflicts
    @transactional
    async def reset_password(
        self, id: int, data: StaffPasswordWrite, actor_id: int
    ) -> None:
        await self.authority.locked_owners()
        actor = await self.authority.access(actor_id, True)
        target = await self.authority.access(id, True)
        if target is None:
            raise missing(id)
        verify_delegation(actor, "update", target.effective_scopes)
        hashed = await self.passwords.hash(data.password.get_secret_value())
        await self.repo.update_row_by_id(
            id, StaffModel.patch(password_hash=hashed)
        )
        await self.repo.revoke_sessions(id)

    def validate_capacity(self, scopes: list[str]) -> None:
        if len(scopes) > self.settings.operations.max_staff_grants:
            raise conflict("staff_grant_capacity", len(scopes))


def verify_delegation(
    actor: StaffAccess | None, level: str, scopes: frozenset[str]
) -> None:
    if actor is None or not actor.staff.is_active:
        raise ForbiddenException(
            message="دسترسی مدیر معتبر نیست.",
            message_code="admin_scope_denied",
        )
    grants = actor.effective_scopes
    if "*" in grants:
        return
    if not grants.intersection({"staff:*", f"staff:{level}"}) or any(
        scope == "*"
        or scope not in grants
        and f"{scope.split(':', 1)[0]}:*" not in grants
        for scope in scopes
    ):
        raise ForbiddenException(
            message="تفویض دسترسی بیش از اختیارات شما مجاز نیست.",
            message_code="staff_delegation_denied",
        )


def missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="مدیر پیدا نشد.",
        message_code="staff_not_found",
        entity="staff",
        identifier="id",
        identifier_value=id,
    )


def conflict(code: str, id: int) -> ConflictException:
    return ConflictException(
        message="وضعیت دسترسی مدیر با درخواست سازگار نیست.",
        message_code=code,
        unique_dict={"id": id},
    )
