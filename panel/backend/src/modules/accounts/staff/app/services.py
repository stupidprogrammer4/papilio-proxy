import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import UnAuthorizedException
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256
from pydantic import SecretStr

from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.domain.dtos import StaffCredentials
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.domain.results import (
    IssuedSession,
    Principal,
    StaffAccess,
)
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader


def _denied() -> UnAuthorizedException:
    return UnAuthorizedException(
        message="نشست مدیریت معتبر نیست.", message_code="admin_unauthorized"
    )


class StaffAuth:
    def __init__(
        self,
        repo: StaffRepository,
        passwords: Passwords,
        settings: PapilioSettings,
        sessions: StaffSessionReader,
    ) -> None:
        self.sessions = sessions
        self.repo = repo
        self.passwords = passwords
        self.settings = settings

    @transactional
    async def login(self, username: str, password: str) -> IssuedSession:
        staff = await self.repo.locked_by_username(username)
        if staff is None or not staff.is_active:
            raise _denied()
        verified = await self.passwords.verify(password, staff.password_hash)
        if not verified:
            raise _denied()
        if staff.password_hash.startswith("scrypt$"):
            upgraded = await self.passwords.hash(password)
            await self.repo.update_row_by_id(
                staff.id, StaffModel.patch(password_hash=upgraded)
            )
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        expires = datetime.now(UTC) + timedelta(
            hours=self.settings.operations.staff_session_hours
        )
        await self.repo.store_session(
            (await asyncio.to_thread(hash_sha256, token)),
            staff.id,
            csrf,
            expires.replace(tzinfo=None),
        )
        direct = await self.repo.grants(staff.id)
        roles = await self.sessions.roles(staff.id)
        grants = StaffAccess(staff, direct, roles).effective_scopes
        return IssuedSession(
            token,
            Principal(staff.id, staff.username, grants, csrf, expires),
        )

    async def current(self, token: str) -> Principal:
        if not token:
            raise _denied()
        stored = await self.sessions.by_token(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if stored is None:
            raise _denied()
        staff, session = stored.staff, stored.session
        now = datetime.now(UTC).replace(tzinfo=None)
        if not staff.is_active or session.expires_at <= now:
            raise _denied()
        direct = await self.repo.grants(staff.id)
        roles = await self.sessions.roles(staff.id)
        grants = StaffAccess(staff, direct, roles).effective_scopes
        return Principal(
            staff.id,
            staff.username,
            grants,
            session.csrf_token,
            session.expires_at.replace(tzinfo=UTC),
        )

    @transactional
    async def logout(self, token: str) -> None:
        if token:
            await self.repo.remove_session(
                (await asyncio.to_thread(hash_sha256, token))
            )

    @transactional
    async def create_owner(self, username: str, password: str) -> None:
        credentials = StaffCredentials(
            username=username, password=SecretStr(password)
        )
        existing = await self.repo.by_username(credentials.username)
        if existing is not None:
            raise ValueError("نام مدیر تکراری است.")
        hashed = await self.passwords.hash(
            credentials.password.get_secret_value()
        )
        staff = await self.repo.create(
            StaffModel(username=username, password_hash=hashed, is_active=True)
        )
        await self.repo.add_grant(staff.id, "*")
