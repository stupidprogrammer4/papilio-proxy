import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import UnAuthorizedException
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256

from src.config.settings import PapilioSettings
from src.modules.accounts.customer_auth.domain.models import (
    CustomerLoginModel,
    CustomerSessionModel,
)
from src.modules.accounts.customer_auth.domain.results import (
    CustomerLoginLink,
    CustomerPrincipal,
    IssuedCustomerSession,
)
from src.modules.accounts.customer_auth.infra.mysql import (
    CustomerLoginRepository,
    CustomerSessionRepository,
)
from src.modules.accounts.customer_auth.infra.readers import (
    CustomerSessionReader,
)
from src.modules.accounts.customers.interfaces import ICustomerService


def denied() -> UnAuthorizedException:
    return UnAuthorizedException(
        message="ورود به حساب مشتری معتبر نیست.",
        message_code="customer_unauthorized",
    )


class CustomerAuthCommand:
    def __init__(
        self,
        logins: CustomerLoginRepository,
        sessions: CustomerSessionRepository,
        reader: CustomerSessionReader,
        customers: ICustomerService,
        settings: PapilioSettings,
    ) -> None:
        self.logins = logins
        self.sessions = sessions
        self.reader = reader
        self.customers = customers
        self.settings = settings

    @transactional
    async def issue_link(self, customer_id: int) -> CustomerLoginLink:
        customer = await self.customers.locked(customer_id)
        if not self.settings.customer_auth.enabled or not customer.is_active:
            raise denied()
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(
            seconds=self.settings.customer_auth.login_seconds
        )
        await self.logins.create(
            CustomerLoginModel(
                token_hash=(await asyncio.to_thread(hash_sha256, token)),
                customer_id=customer_id,
                expires_at=expires.replace(tzinfo=None),
            )
        )
        return CustomerLoginLink(
            url=f"{self.settings.public.customer_portal_origin.rstrip('/')}/account/sign-in#{token}",
            expires_at=expires,
        )

    @transactional
    async def exchange(self, token: str) -> IssuedCustomerSession:
        if not self.settings.customer_auth.enabled:
            raise denied()
        login = await self.logins.get(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if login is None or login.expires_at <= datetime.now(UTC).replace(
            tzinfo=None
        ):
            raise denied()
        customer = await self.customers.locked(login.customer_id)
        login = await self.logins.locked(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if (
            login is None
            or login.customer_id != customer.id
            or login.expires_at <= datetime.now(UTC).replace(tzinfo=None)
        ):
            raise denied()
        if not customer.is_active:
            raise denied()
        await self.logins.remove(login.token_hash)
        session_token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        expires = datetime.now(UTC) + timedelta(
            seconds=self.settings.customer_auth.session_seconds
        )
        await self.sessions.create(
            CustomerSessionModel(
                token_hash=(
                    await asyncio.to_thread(hash_sha256, session_token)
                ),
                customer_id=customer.id,
                csrf_token=csrf,
                expires_at=expires.replace(tzinfo=None),
            )
        )
        return IssuedCustomerSession(
            session_token,
            CustomerPrincipal(
                customer.id, customer.display_name, csrf, expires
            ),
        )

    async def current(self, token: str) -> CustomerPrincipal:
        if not token or not self.settings.customer_auth.enabled:
            raise denied()
        facts = await self.reader.by_token(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if (
            facts is None
            or not facts.customer.is_active
            or facts.session.expires_at
            <= datetime.now(UTC).replace(tzinfo=None)
        ):
            raise denied()
        return CustomerPrincipal(
            facts.customer.id,
            facts.customer.display_name,
            facts.session.csrf_token,
            facts.session.expires_at.replace(tzinfo=UTC),
        )

    @transactional
    async def revoke_customer(self, customer_id: int) -> None:
        await self.logins.remove_customer(customer_id)
        await self.sessions.remove_customer(customer_id)

    @transactional
    async def logout(self, token: str) -> None:
        if token:
            await self.sessions.remove(
                (await asyncio.to_thread(hash_sha256, token))
            )
