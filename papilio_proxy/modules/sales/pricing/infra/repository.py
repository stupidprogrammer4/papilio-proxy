from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from papilio_proxy.config.database import Base, DatabaseConnection, create_mysql_engine
from papilio_proxy.modules.sales.pricing.domain.entities import PricingAssumptions
from papilio_proxy.modules.sales.pricing.infra.tables import PricingAssumptionsModel


class MysqlPricingRepository:
    """MySQL persistence for the editable pricing model; no prices are seeded in code."""

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

    async def get(self) -> PricingAssumptions | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(PricingAssumptionsModel).where(PricingAssumptionsModel.id == 1)
            )
        if row is None:
            return None
        return PricingAssumptions(
            period_days=row.period_days,
            daily_server_cost_rial=row.daily_server_cost_rial,
            included_traffic_gb=row.included_traffic_gb,
            overage_cost_rial_per_gb=row.overage_cost_rial_per_gb,
            target_customers=row.target_customers,
            contingency_basis_points=row.contingency_basis_points,
            target_margin_basis_points=row.target_margin_basis_points,
        )

    async def save(self, value: PricingAssumptions) -> None:
        fields = {
            "period_days": value.period_days,
            "daily_server_cost_rial": value.daily_server_cost_rial,
            "included_traffic_gb": value.included_traffic_gb,
            "overage_cost_rial_per_gb": value.overage_cost_rial_per_gb,
            "target_customers": value.target_customers,
            "contingency_basis_points": value.contingency_basis_points,
            "target_margin_basis_points": value.target_margin_basis_points,
        }
        statement = insert(PricingAssumptionsModel).values(id=1, **fields)
        statement = statement.on_duplicate_key_update(**fields)
        async with self._sessions() as session, session.begin():
            await session.execute(statement)
