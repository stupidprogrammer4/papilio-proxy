from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import or_, select
from sqlmodel import col

from src.modules.network.configurations.infra.tables import ConfigurationTable
from src.modules.network.core_runtime.infra.tables import CoreRuntimeStateTable
from src.modules.network.provisioning.infra.tables import (
    ProvisionRequestTable,
    ProvisionTaskTable,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class CoreProvisioningReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def due_core_ids(
        self,
        before: datetime,
        states: list[str],
        request_states: list[str],
        limit: int,
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(ConfigurationTable.core_id))
            .join(
                ProvisionTaskTable,
                col(ProvisionTaskTable.configuration_id)
                == col(ConfigurationTable.id),
            )
            .join(
                ProvisionRequestTable,
                col(ProvisionRequestTable.id)
                == col(ProvisionTaskTable.request_id),
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id)
                == col(ProvisionRequestTable.subscription_id),
            )
            .outerjoin(
                CoreRuntimeStateTable,
                col(CoreRuntimeStateTable.core_id)
                == col(ConfigurationTable.core_id),
            )
            .where(
                col(ProvisionRequestTable.generation)
                == col(SubscriptionTable.renewal_count),
                or_(
                    col(ProvisionTaskTable.state) != "leased",
                    col(ProvisionTaskTable.claim_until).is_(None),
                    col(ProvisionTaskTable.claim_until) <= before,
                ),
                col(ProvisionTaskTable.state).in_(states),
                col(ProvisionRequestTable.state).in_(request_states),
                col(ProvisionTaskTable.available_at) <= before,
            )
            .group_by(
                col(ConfigurationTable.core_id),
                col(CoreRuntimeStateTable.last_provision_scan_at),
            )
            .order_by(
                col(CoreRuntimeStateTable.last_provision_scan_at),
                col(ConfigurationTable.core_id),
            )
            .limit(limit)
        )
        return list(result.scalars())
