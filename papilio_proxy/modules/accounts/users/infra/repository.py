from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from papilio_proxy.config.database import DatabaseConnection, create_mysql_engine
from papilio_proxy.modules.accounts.users.domain.entities import UnknownUserError, UserBlockedError
from papilio_proxy.modules.accounts.users.infra.tables import UserAccessPolicyModel, UserModel
from papilio_proxy.modules.sales.subscriptions.infra.tables import SubscriptionModel


def subscription_user_is_allowed() -> ColumnElement[bool]:
    return (
        ~select(UserAccessPolicyModel.telegram_id)
        .where(
            UserAccessPolicyModel.telegram_id == SubscriptionModel.telegram_id,
            UserAccessPolicyModel.is_blocked.is_(True),
        )
        .exists()
    )


async def require_user_access(session: AsyncSession, telegram_id: int) -> None:
    # Serialize provisioning/order creation with admin policy changes.
    user = await session.get(UserModel, telegram_id, with_for_update=True)
    if user is None:
        raise UnknownUserError("کاربر پیدا نشد.")
    policy = await session.get(UserAccessPolicyModel, telegram_id, with_for_update=True)
    if policy is not None and policy.is_blocked:
        raise UserBlockedError("دسترسی شما مسدود شده است؛ با پشتیبانی تماس بگیرید.")


class MysqlUserAccessRepository:
    def __init__(self, database_url: str | DatabaseConnection) -> None:
        self._owns_engine = isinstance(database_url, str)
        self._engine = create_mysql_engine(database_url)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self) -> None:
        if self._owns_engine:
            await self._engine.dispose()

    async def set_blocked(
        self,
        telegram_id: int,
        blocked: bool,
        reason: str,
        actor: str,
    ) -> list[str]:
        async with self._sessions() as session, session.begin():
            user = await session.get(UserModel, telegram_id, with_for_update=True)
            if user is None:
                raise UnknownUserError("کاربر پیدا نشد.")
            policy = await session.get(UserAccessPolicyModel, telegram_id)
            if policy is None:
                policy = UserAccessPolicyModel(telegram_id=telegram_id)
                session.add(policy)
            policy.is_blocked = blocked
            policy.reason = reason
            policy.changed_by = actor
            policy.updated_at = datetime.now(UTC).replace(tzinfo=None)
            identifiers = await session.scalars(
                select(SubscriptionModel.id).where(
                    SubscriptionModel.telegram_id == telegram_id,
                )
            )
            return list(identifiers.all())
