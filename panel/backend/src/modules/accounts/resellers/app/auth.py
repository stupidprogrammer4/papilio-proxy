import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256, secure_compare

from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.app.policies import (
    ResellerCapacity,
    conflict,
    denied,
)
from src.modules.accounts.resellers.domain.dtos import (
    ResellerCredentials,
    ResellerPolicy,
    ResellerScopes,
)
from src.modules.accounts.resellers.domain.models import ResellerSessionModel
from src.modules.accounts.resellers.domain.results import (
    IssuedResellerSession,
    ResellerPrincipal,
)
from src.modules.accounts.resellers.infra.mysql import (
    ResellerAccountRepository,
    ResellerRepository,
    ResellerSessionRepository,
)
from src.modules.accounts.resellers.infra.readers import ResellerSessionReader
from src.modules.accounts.staff.app.passwords import Passwords


class ResellerAuthCommand:
    def __init__(
        self,
        accounts: ResellerAccountRepository,
        resellers: ResellerRepository,
        sessions: ResellerSessionRepository,
        passwords: Passwords,
        settings: PapilioSettings,
    ) -> None:
        self.accounts = accounts
        self.resellers = resellers
        self.sessions = sessions
        self.passwords = passwords
        self.settings = settings

    @transactional
    async def login(self, data: ResellerCredentials) -> IssuedResellerSession:
        capacity = self.settings.resellers
        if capacity is None or not capacity.enabled:
            raise denied()
        observed = await self.accounts.by_username(data.username)
        if observed is None or not observed.is_active:
            raise denied()
        valid = await self.passwords.verify(
            data.password.get_secret_value(), observed.password_hash
        )
        if not valid:
            raise denied()
        verified_hash = observed.password_hash
        reseller = await self.resellers.locked(observed.reseller_id)
        account = await self.accounts.owned(
            observed.reseller_id, observed.id, True
        )
        if (
            reseller is None
            or not reseller.login_enabled
            or account is None
            or not account.is_active
            or not secure_compare(account.password_hash, verified_hash)
        ):
            raise denied()
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        ResellerCapacity.validate(policy, capacity)
        scopes = ResellerScopes.model_validate_json(account.scopes_json)
        ResellerCapacity.scopes(scopes, capacity)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        await self.sessions.remove_obsolete(
            account.id, account.revision, reseller.access_revision, now
        )
        active = await self.sessions.active(
            account.id, now, capacity.max_sessions_per_account + 1
        )
        if len(active) > capacity.max_sessions_per_account:
            raise conflict("reseller_session_capacity")
        if len(active) >= policy.max_sessions_per_account:
            if policy.session_limit_mode == "reject_new":
                raise conflict("reseller_session_capacity")
            retire = len(active) - policy.max_sessions_per_account + 1
            await self.sessions.remove_many(
                [row.token_hash for row in active[:retire]]
            )
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        expiry = now + timedelta(seconds=capacity.session_seconds)
        await self.sessions.create(
            ResellerSessionModel(
                token_hash=(await asyncio.to_thread(hash_sha256, token)),
                account_id=account.id,
                account_revision=account.revision,
                reseller_access_revision=reseller.access_revision,
                csrf_token=csrf,
                expires_at=expiry,
            )
        )
        return IssuedResellerSession(
            token,
            ResellerPrincipal(
                reseller.id,
                account.id,
                reseller.title,
                account.username,
                frozenset(scopes.scopes),
                csrf,
                expiry.replace(tzinfo=UTC),
                account.revision,
                reseller.access_revision,
            ),
        )

    @transactional
    async def logout(self, token: str) -> None:
        if token:
            await self.sessions.remove(
                (await asyncio.to_thread(hash_sha256, token))
            )


class ResellerAuthQuery:
    def __init__(
        self,
        reader: ResellerSessionReader,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.settings = settings

    async def current(self, token: str) -> ResellerPrincipal:
        capacity = self.settings.resellers
        if not token or capacity is None or not capacity.enabled:
            raise denied()
        facts = await self.reader.by_token(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if (
            facts is None
            or not facts.account.is_active
            or not facts.reseller.login_enabled
            or facts.session.account_revision != facts.account.revision
            or facts.session.reseller_access_revision
            != facts.reseller.access_revision
            or facts.session.expires_at
            <= datetime.now(UTC).replace(tzinfo=None)
        ):
            raise denied()
        scopes = ResellerScopes.model_validate_json(facts.account.scopes_json)
        return ResellerPrincipal(
            facts.reseller.id,
            facts.account.id,
            facts.reseller.title,
            facts.account.username,
            frozenset(scopes.scopes),
            facts.session.csrf_token,
            facts.session.expires_at.replace(tzinfo=UTC),
            facts.account.revision,
            facts.reseller.access_revision,
        )
