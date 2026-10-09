from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlmodel import col

from src.modules.sales.attention.domain.models import (
    SubscriptionAttentionModel,
)
from src.modules.sales.attention.infra.tables import SubscriptionAttentionTable


class SubscriptionAttentionRepository(
    MySQLPersistenceRepository[SubscriptionAttentionModel]
):
    table = SubscriptionAttentionTable

    async def store(
        self, data: SubscriptionAttentionModel
    ) -> SubscriptionAttentionModel:
        statement = insert(SubscriptionAttentionTable).values(
            **data.model_dump(exclude_unset=True)
        )
        await self.uow.execute(
            statement.on_duplicate_key_update(
                **data.to_changes(), updated_at=func.current_timestamp()
            )
        )
        result = await self.uow.execute(
            select(SubscriptionAttentionTable)
            .where(
                col(SubscriptionAttentionTable.subscription_id)
                == data.subscription_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        stored = result.scalar_one()
        return stored
