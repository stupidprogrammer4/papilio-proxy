from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import and_, select
from sqlmodel import col

from src.modules.accounts.customers.infra.tables import CustomerTable
from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.network.core_runtime.domain.facts import (
    RuntimeConfigurationFacts,
    RuntimeProfileFacts,
    RuntimeSnapshotFacts,
)
from src.modules.network.core_runtime.infra.tables import (
    CoreRuntimeCommandTable,
)
from src.modules.network.provisioning.infra.tables import (
    ProvisionRequestTable,
    ProvisionTaskTable,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class RuntimeSnapshotReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def facts(
        self, core_id: int, configuration_limit: int, profile_limit: int
    ) -> RuntimeSnapshotFacts:
        configurations = await self.uow.execute(
            select(ConfigurationTable)
            .where(col(ConfigurationTable.core_id) == core_id)
            .order_by(col(ConfigurationTable.id))
            .limit(configuration_limit)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        profiles = await self.uow.execute(
            select(
                ProfileTable,
                SubscriptionTable,
                CustomerTable,
                ProvisionRequestTable,
                ProvisionTaskTable,
            )
            .join(
                ConfigurationTable,
                col(ConfigurationTable.id)
                == col(ProfileTable.configuration_id),
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id) == col(ProfileTable.subscription_id),
            )
            .join(
                CustomerTable,
                col(CustomerTable.id) == col(SubscriptionTable.customer_id),
            )
            .outerjoin(
                ProvisionRequestTable,
                and_(
                    col(ProvisionRequestTable.subscription_id)
                    == col(SubscriptionTable.id),
                    col(ProvisionRequestTable.generation)
                    == col(SubscriptionTable.renewal_count),
                ),
            )
            .outerjoin(
                ProvisionTaskTable,
                and_(
                    col(ProvisionTaskTable.request_id)
                    == col(ProvisionRequestTable.id),
                    col(ProvisionTaskTable.profile_id) == col(ProfileTable.id),
                ),
            )
            .where(col(ConfigurationTable.core_id) == core_id)
            .order_by(col(ProfileTable.id))
            .limit(profile_limit)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return RuntimeSnapshotFacts(
            tuple(
                RuntimeConfigurationFacts(
                    c.id,
                    c.revision,
                    c.listen_port,
                    c.port_network,
                    c.protocol,
                    c.encrypted_settings,
                )
                for c in configurations.scalars()
            ),
            tuple(
                RuntimeProfileFacts(
                    row.ProfileTable.id,
                    row.ProfileTable.configuration_id,
                    row.ProfileTable.encrypted_credentials,
                    row.ProfileTable.client_address,
                    row.SubscriptionTable.id,
                    row.SubscriptionTable.renewal_count,
                    row.SubscriptionTable.quota_bytes,
                    row.SubscriptionTable.used_bytes,
                    row.SubscriptionTable.expires_at,
                    row.SubscriptionTable.status,
                    row.CustomerTable.services_enabled,
                    row.ProvisionRequestTable.state
                    if row.ProvisionRequestTable
                    else None,
                    row.ProvisionRequestTable.policy_json
                    if row.ProvisionRequestTable
                    else None,
                    row.ProvisionRequestTable.activated_at
                    if row.ProvisionRequestTable
                    else None,
                    row.SubscriptionTable.duration_days,
                    row.CustomerTable.service_hold_pending,
                    row.ProvisionTaskTable.action
                    if row.ProvisionTaskTable
                    else None,
                    row.ProvisionTaskTable.encrypted_payload
                    if row.ProvisionTaskTable
                    else None,
                    row.SubscriptionTable.quota_policy_json,
                )
                for row in profiles
            ),
        )

    async def due_ids(self, before: datetime, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(CoreRuntimeCommandTable.id))
            .where(
                col(CoreRuntimeCommandTable.state) == "leased",
                col(CoreRuntimeCommandTable.claim_until) <= before,
            )
            .order_by(
                col(CoreRuntimeCommandTable.claim_until),
                col(CoreRuntimeCommandTable.id),
            )
            .limit(limit)
        )
        return list(result.scalars())
