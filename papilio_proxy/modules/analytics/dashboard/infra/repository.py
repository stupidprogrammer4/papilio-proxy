from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from papilio_proxy.config.database import DatabaseConnection, create_mysql_engine
from papilio_proxy.modules.accounts.users.infra.repository import subscription_user_is_allowed
from papilio_proxy.modules.accounts.users.infra.tables import UserModel
from papilio_proxy.modules.analytics.dashboard.app.services import (
    DashboardRepository,
    DashboardSnapshot,
)
from papilio_proxy.modules.sales.subscriptions.infra.tables import SubscriptionModel


class MysqlDashboardRepository(DashboardRepository):
    """Read-only dashboard queries backed by the shared SQLAlchemy pool."""

    def __init__(self, database_url: str | DatabaseConnection) -> None:
        self._owns_engine = isinstance(database_url, str)
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self) -> None:
        if self._owns_engine:
            await self._engine.dispose()

    async def snapshot(self) -> DashboardSnapshot:
        async with self._session_factory() as session:
            user_count = await session.scalar(select(func.count(UserModel.telegram_id)))
            overview = (
                await session.execute(
                    select(
                        func.count(SubscriptionModel.id),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        (SubscriptionModel.status == "active")
                                        & subscription_user_is_allowed(),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                        func.coalesce(
                            func.sum(
                                case((SubscriptionModel.status == "pending_payment", 1), else_=0)
                            ),
                            0,
                        ),
                        func.coalesce(func.sum(SubscriptionModel.traffic_used_bytes), 0),
                        func.coalesce(func.sum(SubscriptionModel.traffic_limit_bytes), 0),
                    )
                )
            ).one()
            users = (
                await session.execute(
                    select(
                        UserModel.telegram_id,
                        UserModel.display_name,
                        UserModel.username,
                        func.count(SubscriptionModel.id),
                    )
                    .outerjoin(
                        SubscriptionModel, SubscriptionModel.telegram_id == UserModel.telegram_id
                    )
                    .group_by(
                        UserModel.telegram_id,
                        UserModel.display_name,
                        UserModel.username,
                        UserModel.created_at,
                    )
                    .order_by(UserModel.created_at.desc())
                    .limit(8)
                )
            ).all()
            subscriptions = (
                await session.execute(
                    select(
                        SubscriptionModel.id,
                        SubscriptionModel.telegram_id,
                        SubscriptionModel.plan_code,
                        SubscriptionModel.status,
                        SubscriptionModel.traffic_used_bytes,
                        SubscriptionModel.traffic_limit_bytes,
                    )
                    .order_by(SubscriptionModel.created_at.desc())
                    .limit(12)
                )
            ).all()
        return DashboardSnapshot(
            int(user_count or 0),
            int(overview[0] or 0),
            int(overview[1] or 0),
            int(overview[2] or 0),
            int(overview[3] or 0),
            int(overview[4] or 0),
            [
                (int(row[0]), str(row[1]), str(row[2]) if row[2] else None, int(row[3]))
                for row in users
            ],
            [
                (str(row[0]), int(row[1]), str(row[2]), str(row[3]), int(row[4]), int(row[5]))
                for row in subscriptions
            ],
        )
