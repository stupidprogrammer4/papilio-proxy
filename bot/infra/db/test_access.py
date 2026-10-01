from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.models import Base, SubscriptionModel, SubscriptionTermsModel, UserModel
from bot.infra.db.pool import create_mysql_engine
from bot.models.subscriptions import SubscriptionStatus


class MysqlTestAccessRepository:
    """Persist an admin-only, zero-revenue pilot entitlement in the normal order flow."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_mysql_engine(database_url)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    async def grant(self, telegram_id: int, quota_bytes: int, duration_days: int) -> str:
        if quota_bytes <= 0 or not 1 <= duration_days <= 7:
            raise ValueError("Invalid pilot entitlement")
        async with self._sessions() as session, session.begin():
            user = await session.scalar(
                select(UserModel).where(UserModel.telegram_id == telegram_id).with_for_update()
            )
            if user is None:
                raise ValueError("Admin must start the Telegram bot before receiving a pilot")
            existing = await session.scalar(
                select(SubscriptionModel.id).where(
                    SubscriptionModel.telegram_id == telegram_id,
                    SubscriptionModel.plan_code == "PILOT_TEST",
                    SubscriptionModel.status.in_((
                        SubscriptionStatus.TEST_AWAITING_PROVISIONING.value,
                        SubscriptionStatus.ACTIVE.value,
                    )),
                )
            )
            if existing is not None:
                raise ValueError("An active pilot entitlement already exists for this admin")
            order_id = str(uuid4())
            session.add(SubscriptionModel(
                id=order_id,
                telegram_id=telegram_id,
                plan_code="PILOT_TEST",
                protocol="both",
                status=SubscriptionStatus.TEST_AWAITING_PROVISIONING.value,
                traffic_limit_bytes=quota_bytes,
                traffic_used_bytes=0,
                price_rial=0,
                expires_at=None,
                created_at=datetime.now(UTC).replace(tzinfo=None),
            ))
            session.add(SubscriptionTermsModel(
                subscription_id=order_id,
                duration_days=duration_days,
            ))
        return order_id
