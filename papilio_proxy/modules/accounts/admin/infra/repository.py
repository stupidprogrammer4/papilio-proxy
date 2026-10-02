from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from papilio_proxy.config.database import Base, DatabaseConnection, create_mysql_engine
from papilio_proxy.modules.accounts.admin.domain.entities import (
    AdminFinancialSnapshot,
    AdminLogin,
    AdminLoginDenied,
    AdminOrderRow,
    AdminSession,
    AdminUserRow,
)
from papilio_proxy.modules.accounts.admin.infra.tables import (
    WebAdminAccountModel,
    WebAdminSessionModel,
)
from papilio_proxy.modules.accounts.users.infra.tables import UserAccessPolicyModel, UserModel
from papilio_proxy.modules.sales.payments.infra.tables import (
    ManualSettlementModel,
    PaymentReceiptModel,
)
from papilio_proxy.modules.sales.subscriptions.infra.tables import SubscriptionModel

SESSION_LIFETIME = timedelta(hours=12)
LOCK_TIME = timedelta(minutes=15)
MAX_ATTEMPTS = 5
_FAKE_SALT = bytes.fromhex("b5a687d474cedcc5966db0beed823760")


def _digest(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


class MysqlAdminWebRepository:
    """Admin auth, sessions and paged read models; all queries remain in infra."""

    def __init__(self, database_url: str | DatabaseConnection) -> None:
        self._owns_engine = isinstance(database_url, str)
        self._engine = create_mysql_engine(database_url)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        if self._owns_engine:
            await self._engine.dispose()

    async def set_password(self, username: str, password: str) -> None:
        """Operator-only bootstrap/change; never callable from the public API."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username) or len(password) < 8:
            raise ValueError("Invalid admin username or password")
        salt = secrets.token_bytes(16)
        password_hash = await asyncio.to_thread(_digest, password, salt)
        async with self._sessions() as session, session.begin():
            account = await session.get(WebAdminAccountModel, username, with_for_update=True)
            if account is None:
                session.add(
                    WebAdminAccountModel(
                        username=username,
                        password_salt=salt.hex(),
                        password_hash=password_hash,
                        failed_attempts=0,
                    )
                )
            else:
                account.password_salt = salt.hex()
                account.password_hash = password_hash
                account.failed_attempts = 0
                account.locked_until = None
                await session.execute(
                    delete(WebAdminSessionModel).where(WebAdminSessionModel.username == username)
                )

    async def login(self, username: str, password: str) -> AdminLogin:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        expiry = now + SESSION_LIFETIME
        async with self._sessions() as session, session.begin():
            account = await session.scalar(
                select(WebAdminAccountModel)
                .where(WebAdminAccountModel.username == username)
                .with_for_update()
            )
            if account is None:
                await asyncio.to_thread(_digest, password, _FAKE_SALT)
                raise AdminLoginDenied("Invalid admin credentials")
            if account.locked_until is not None and account.locked_until > _utc_naive(now):
                raise AdminLoginDenied("Admin account is temporarily locked")
            attempt = await asyncio.to_thread(
                _digest, password, bytes.fromhex(account.password_salt)
            )
            if not hmac.compare_digest(attempt, account.password_hash):
                account.failed_attempts += 1
                if account.failed_attempts >= MAX_ATTEMPTS:
                    account.failed_attempts = 0
                    account.locked_until = _utc_naive(now + LOCK_TIME)
                # Do not raise before the transaction commits the failure counter.
                denied = True
            else:
                denied = False
                account.failed_attempts = 0
                account.locked_until = None
                await session.execute(
                    delete(WebAdminSessionModel).where(
                        WebAdminSessionModel.expires_at < _utc_naive(now)
                    )
                )
                session.add(
                    WebAdminSessionModel(
                        token_digest=hashlib.sha256(token.encode()).hexdigest(),
                        username=username,
                        csrf_token=csrf,
                        expires_at=_utc_naive(expiry),
                    )
                )
        if denied:
            raise AdminLoginDenied("Invalid admin credentials")
        return AdminLogin(token, AdminSession(username, csrf, expiry))

    async def get_session(self, token: str) -> AdminSession | None:
        if not token or len(token) > 128:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with self._sessions() as session:
            row = await session.get(WebAdminSessionModel, digest)
        if row is None or row.expires_at <= _utc_naive(datetime.now(UTC)):
            return None
        return AdminSession(row.username, row.csrf_token, row.expires_at.replace(tzinfo=UTC))

    async def logout(self, token: str) -> None:
        if not token or len(token) > 128:
            return
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with self._sessions() as session, session.begin():
            await session.execute(
                delete(WebAdminSessionModel).where(WebAdminSessionModel.token_digest == digest)
            )

    async def finances(self) -> AdminFinancialSnapshot:
        statement = select(
            func.count(ManualSettlementModel.order_id),
            func.coalesce(func.sum(ManualSettlementModel.amount_rial), 0),
            select(func.count(PaymentReceiptModel.id))
            .where(PaymentReceiptModel.status == "pending")
            .scalar_subquery(),
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).one()
        return AdminFinancialSnapshot(int(row[0]), int(row[1]), int(row[2]))

    async def list_users(
        self, query: str = "", *, limit: int = 50, offset: int = 0
    ) -> list[AdminUserRow]:
        statement = (
            select(
                UserModel.telegram_id,
                UserModel.display_name,
                UserModel.username,
                func.count(SubscriptionModel.id),
                UserModel.created_at,
                UserAccessPolicyModel.is_blocked,
                UserAccessPolicyModel.reason,
            )
            .outerjoin(SubscriptionModel, SubscriptionModel.telegram_id == UserModel.telegram_id)
            .outerjoin(
                UserAccessPolicyModel, UserAccessPolicyModel.telegram_id == UserModel.telegram_id
            )
            .group_by(
                UserModel.telegram_id,
                UserModel.display_name,
                UserModel.username,
                UserModel.created_at,
                UserAccessPolicyModel.is_blocked,
                UserAccessPolicyModel.reason,
            )
            .order_by(UserModel.created_at.desc(), UserModel.telegram_id.desc())
            .limit(limit)
            .offset(offset)
        )
        if query:
            pattern = f"%{query[:64]}%"
            conditions: list[ColumnElement[bool]] = [
                UserModel.display_name.like(pattern),
                UserModel.username.like(pattern),
            ]
            if query.isascii() and query.isdecimal() and len(query) <= 18:
                conditions.append(UserModel.telegram_id == int(query))
            statement = statement.where(or_(*conditions))
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        return [
            AdminUserRow(
                int(row[0]),
                str(row[1]),
                row[2],
                int(row[3]),
                row[4].replace(tzinfo=UTC),
                bool(row[5]),
                row[6] or "",
            )
            for row in rows
        ]

    async def list_orders(self, *, limit: int = 50, offset: int = 0) -> list[AdminOrderRow]:
        receipt_status = (
            select(PaymentReceiptModel.status)
            .where(PaymentReceiptModel.order_id == SubscriptionModel.id)
            .order_by(PaymentReceiptModel.created_at.desc(), PaymentReceiptModel.id.desc())
            .limit(1)
            .correlate(SubscriptionModel)
            .scalar_subquery()
        )
        statement = (
            select(SubscriptionModel, receipt_status, UserAccessPolicyModel.is_blocked)
            .outerjoin(
                UserAccessPolicyModel,
                UserAccessPolicyModel.telegram_id == SubscriptionModel.telegram_id,
            )
            .order_by(SubscriptionModel.created_at.desc(), SubscriptionModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        return [
            AdminOrderRow(
                order.id,
                order.telegram_id,
                order.plan_code,
                order.status,
                order.price_rial,
                order.traffic_limit_bytes,
                order.traffic_used_bytes,
                order.created_at.replace(tzinfo=UTC),
                order.expires_at.replace(tzinfo=UTC) if order.expires_at else None,
                payment_status,
                bool(blocked),
            )
            for order, payment_status, blocked in rows
        ]
