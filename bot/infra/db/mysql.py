from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.models import (
    Base,
    BotBrandingModel,
    PlanModel,
    SubscriptionModel,
    UserModel,
)
from bot.infra.db.pool import create_mysql_engine
from bot.models.branding import DEFAULT_BRANDING, BotBranding
from bot.services.subscriptions import (
    Plan,
    PlanRepository,
    Protocol,
    Subscription,
    SubscriptionRepository,
    SubscriptionStatus,
    TelegramUser,
)


def _to_database_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None)


def _from_database_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC)


class MysqlSubscriptionRepository(SubscriptionRepository, PlanRepository):
    """SQLAlchemy adapter for the single MySQL database used by Papilio."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        statement = insert(BotBrandingModel).values(
            id=1,
            name=DEFAULT_BRANDING.name,
            short_description=DEFAULT_BRANDING.short_description,
            description=DEFAULT_BRANDING.description,
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement.prefix_with("IGNORE"))

    async def close(self) -> None:
        await self._engine.dispose()

    async def get_branding(self) -> BotBranding:
        statement = select(BotBrandingModel).where(BotBrandingModel.id == 1)
        async with self._session_factory() as session:
            record = await session.scalar(statement)
        if record is None:
            raise RuntimeError("Bot branding has not been initialized")
        return BotBranding(
            name=record.name,
            short_description=record.short_description,
            description=record.description,
        )

    async def save_branding(self, branding: BotBranding) -> None:
        statement = (
            update(BotBrandingModel)
            .where(BotBrandingModel.id == 1)
            .values(
                name=branding.name,
                short_description=branding.short_description,
                description=branding.description,
            )
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def upsert_user(self, user: TelegramUser) -> None:
        statement = insert(UserModel).values(
            telegram_id=user.telegram_id,
            display_name=user.display_name,
            username=user.username,
        )
        statement = statement.on_duplicate_key_update(
            display_name=statement.inserted.display_name,
            username=statement.inserted.username,
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def list_for_user(self, telegram_id: int) -> list[Subscription]:
        statement = select(SubscriptionModel).where(SubscriptionModel.telegram_id == telegram_id)
        statement = statement.order_by(SubscriptionModel.created_at.desc())
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            records = result.all()
        return [self._subscription(record) for record in records]

    async def list(self, *, active_only: bool = True) -> list[Plan]:
        statement = select(PlanModel)
        if active_only:
            statement = statement.where(PlanModel.is_active.is_(True))
        statement = statement.order_by(PlanModel.sort_order, PlanModel.code)
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            records = result.all()
        return [self._plan(record) for record in records]

    async def get(self, code: str) -> Plan | None:
        statement = select(PlanModel).where(PlanModel.code == code)
        async with self._session_factory() as session:
            record = await session.scalar(statement)
        return self._plan(record) if record else None

    async def save(self, plan: Plan) -> None:
        statement = insert(PlanModel).values(
            code=plan.code,
            title=plan.title,
            traffic_gb=plan.traffic_gb,
            duration_days=plan.duration_days,
            price_rial=plan.price_rial,
            is_active=plan.is_active,
            sort_order=plan.sort_order,
        )
        statement = statement.on_duplicate_key_update(
            title=statement.inserted.title,
            traffic_gb=statement.inserted.traffic_gb,
            duration_days=statement.inserted.duration_days,
            price_rial=statement.inserted.price_rial,
            is_active=statement.inserted.is_active,
            sort_order=statement.inserted.sort_order,
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def set_active(self, code: str, is_active: bool) -> None:
        statement = update(PlanModel).where(PlanModel.code == code).values(is_active=is_active)
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def delete(self, code: str) -> None:
        statement = delete(PlanModel).where(PlanModel.code == code)
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    @staticmethod
    def _plan(record: PlanModel) -> Plan:
        return Plan(
            code=record.code,
            title=record.title,
            traffic_gb=record.traffic_gb,
            duration_days=record.duration_days,
            price_rial=record.price_rial,
            is_active=record.is_active,
            sort_order=record.sort_order,
        )

    async def create(self, subscription: Subscription) -> None:
        model = SubscriptionModel(
            id=subscription.id,
            telegram_id=subscription.telegram_id,
            plan_code=subscription.plan_code,
            protocol=subscription.protocol.value,
            status=subscription.status.value,
            traffic_limit_bytes=subscription.traffic_limit_bytes,
            traffic_used_bytes=subscription.traffic_used_bytes,
            price_rial=subscription.price_rial,
            expires_at=_to_database_datetime(subscription.expires_at),
            created_at=_to_database_datetime(subscription.created_at),
        )
        async with self._session_factory() as session, session.begin():
            session.add(model)

    @staticmethod
    def _subscription(record: SubscriptionModel) -> Subscription:
        created_at = _from_database_datetime(record.created_at)
        assert created_at is not None
        return Subscription(
            id=record.id,
            telegram_id=record.telegram_id,
            plan_code=record.plan_code,
            protocol=Protocol(record.protocol),
            status=SubscriptionStatus(record.status),
            traffic_limit_bytes=record.traffic_limit_bytes,
            traffic_used_bytes=record.traffic_used_bytes,
            expires_at=_from_database_datetime(record.expires_at),
            created_at=created_at,
            price_rial=record.price_rial,
        )
