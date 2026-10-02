from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from papilio_proxy.config.database import Base, DatabaseConnection, create_mysql_engine
from papilio_proxy.modules.accounts.users.infra.repository import require_user_access
from papilio_proxy.modules.accounts.users.infra.tables import UserModel
from papilio_proxy.modules.sales.subscriptions.app.services import (
    Plan,
    PlanRepository,
    Protocol,
    Subscription,
    SubscriptionRepository,
    SubscriptionStatus,
    TelegramUser,
)
from papilio_proxy.modules.sales.subscriptions.infra.tables import (
    PlanModel,
    PlanVisualModel,
    SubscriptionModel,
    SubscriptionTermsModel,
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

    def __init__(self, database_url: str | DatabaseConnection) -> None:
        self._owns_engine = isinstance(database_url, str)
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        if self._owns_engine:
            await self._engine.dispose()

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

    async def list_for_user(
        self,
        telegram_id: int,
        *,
        statuses: frozenset[SubscriptionStatus] | None = None,
    ) -> list[Subscription]:
        statement = select(SubscriptionModel).where(SubscriptionModel.telegram_id == telegram_id)
        if statuses is not None:
            statement = statement.where(
                SubscriptionModel.status.in_([status.value for status in statuses])
            )
        statement = statement.order_by(SubscriptionModel.created_at.desc())
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            records = result.all()
        return [self._subscription(record) for record in records]

    async def list(self, *, active_only: bool = True) -> list[Plan]:
        statement = select(PlanModel, PlanVisualModel.emoji).outerjoin(
            PlanVisualModel, PlanVisualModel.plan_code == PlanModel.code
        )
        if active_only:
            statement = statement.where(PlanModel.is_active.is_(True))
        statement = statement.order_by(PlanModel.sort_order, PlanModel.code)
        async with self._session_factory() as session:
            records = (await session.execute(statement)).all()
        return [self._plan(record, emoji) for record, emoji in records]

    async def get(self, code: str) -> Plan | None:
        statement = (
            select(PlanModel, PlanVisualModel.emoji)
            .outerjoin(PlanVisualModel, PlanVisualModel.plan_code == PlanModel.code)
            .where(PlanModel.code == code)
        )
        async with self._session_factory() as session:
            record = (await session.execute(statement)).one_or_none()
        return self._plan(*record) if record else None

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
        visual = insert(PlanVisualModel).values(plan_code=plan.code, emoji=plan.emoji)
        visual = visual.on_duplicate_key_update(emoji=visual.inserted.emoji)
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)
            await session.execute(visual)

    async def update_prices(
        self, new_prices_rial: Mapping[str, int], expected_prices_rial: Mapping[str, int]
    ) -> None:
        """Atomically update an explicitly checked catalog subset; existing orders keep snapshots."""
        codes = set(new_prices_rial)
        if not codes or codes != set(expected_prices_rial):
            raise ValueError("Price update requires matching catalog codes")
        if any(
            isinstance(amount, bool) or amount <= 0 or amount % 10
            for amount in new_prices_rial.values()
        ):
            raise ValueError("Prices must be positive rial amounts divisible by ten")
        async with self._session_factory() as session, session.begin():
            result = await session.scalars(
                select(PlanModel).where(PlanModel.code.in_(codes)).with_for_update()
            )
            rows = {row.code: row for row in result.all()}
            if set(rows) != codes or any(
                rows[code].price_rial != expected_prices_rial[code] for code in codes
            ):
                raise ValueError("Catalog changed; prices were not updated")
            for code in codes:
                rows[code].price_rial = new_prices_rial[code]

    async def set_active(self, code: str, is_active: bool) -> None:
        statement = update(PlanModel).where(PlanModel.code == code).values(is_active=is_active)
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def delete(self, code: str) -> None:
        statement = delete(PlanModel).where(PlanModel.code == code)
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    @staticmethod
    def _plan(record: PlanModel, emoji: str | None = None) -> Plan:
        return Plan(
            code=record.code,
            title=record.title,
            traffic_gb=record.traffic_gb,
            duration_days=record.duration_days,
            price_rial=record.price_rial,
            is_active=record.is_active,
            sort_order=record.sort_order,
            emoji=emoji or "🦋",
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
        if subscription.duration_days <= 0:
            raise ValueError("A purchased duration snapshot is required")
        async with self._session_factory() as session, session.begin():
            await require_user_access(session, subscription.telegram_id)
            session.add(model)
            session.add(
                SubscriptionTermsModel(
                    subscription_id=subscription.id,
                    duration_days=subscription.duration_days,
                )
            )

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
