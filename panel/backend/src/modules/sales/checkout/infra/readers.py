from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.accounts.customers.infra.tables import CustomerTable
from src.modules.accounts.resellers.infra.tables import ResellerCustomerTable
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.billing.wallet.infra.tables import TopupTable, WalletTable
from src.modules.network.configurations.infra.tables import ConfigurationTable
from src.modules.network.nodes.infra.tables import NodeTable
from src.modules.network.routing.infra.tables import (
    HostGroupTable,
    HostMembershipTable,
    HostTable,
)
from src.modules.sales.catalog.infra.tables import PlanTable
from src.modules.sales.checkout.domain.facts import (
    CheckoutMembershipFacts,
    CheckoutOfferFacts,
)


class CheckoutOfferReader:
    """Declared current customer, plan and complete membership facts."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def customer_plan_current(
        self, customer_id: int, plan_id: int
    ) -> CheckoutOfferFacts | None:
        result = await self.uow.execute(
            select(CustomerTable)
            .where(col(CustomerTable.id) == customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        customer = result.scalar_one_or_none()
        if customer is None:
            return None
        result = await self.uow.execute(
            select(PlanTable)
            .where(col(PlanTable.id) == plan_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        plan = result.scalar_one_or_none()
        if plan is None:
            return None
        return CheckoutOfferFacts(customer, plan, [])

    async def current(
        self, customer_id: int, plan_id: int, limit: int
    ) -> CheckoutOfferFacts | None:
        facts = await self.customer_plan_current(customer_id, plan_id)
        if facts is None:
            return None
        result = await self.product_current(facts, limit)
        return result

    async def product_current(
        self, facts: CheckoutOfferFacts, limit: int
    ) -> CheckoutOfferFacts:
        customer, plan = facts.customer, facts.plan
        if plan.group_id is None:
            return CheckoutOfferFacts(customer, plan, [])
        # Product relationship locks never acquire Node/Core/Configuration
        # after Customer; runtime capture owns their operational lock order.
        result = await self.uow.execute(
            select(HostGroupTable)
            .where(col(HostGroupTable.id) == plan.group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        group = result.scalar_one_or_none()
        group_enabled = group is not None and group.is_enabled
        result = await self.uow.execute(
            select(HostMembershipTable)
            .where(col(HostMembershipTable.group_id) == plan.group_id)
            .order_by(col(HostMembershipTable.id))
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        memberships = [
            (row.host_id, row.is_enabled) for row in result.scalars().all()
        ]
        result = await self.uow.execute(
            select(HostTable)
            .where(
                col(HostTable.id).in_([host_id for host_id, _ in memberships])
            )
            .order_by(col(HostTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        hosts = {
            row.id: (row.configuration_id, row.is_enabled)
            for row in result.scalars().all()
        }
        # Protocol is immutable. Current scalar Node/Configuration reads
        # use nonblocking share locks: runtime owns Node before Customer, so
        # checkout must never wait on Node after holding Customer.
        result = await self.uow.execute(
            select(
                col(ConfigurationTable.id),
                col(ConfigurationTable.protocol),
                col(NodeTable.is_enabled),
            )
            .join(
                NodeTable, col(NodeTable.id) == col(ConfigurationTable.node_id)
            )
            .where(
                col(ConfigurationTable.id).in_(
                    [
                        configuration_id
                        for configuration_id, _ in hosts.values()
                    ]
                )
            )
            .suffix_with("FOR SHARE NOWAIT", dialect="mysql")
        )
        configurations = {
            row.id: (row.protocol, row.is_enabled) for row in result
        }
        membership_facts: list[CheckoutMembershipFacts] = []
        for host_id, selected in memberships:
            configuration_id, host_enabled = hosts[host_id]
            protocol, node_enabled = configurations[configuration_id]
            membership_facts.append(
                CheckoutMembershipFacts(
                    configuration_id,
                    protocol,
                    selected,
                    group_enabled
                    and selected
                    and host_enabled
                    and node_enabled,
                )
            )
        return CheckoutOfferFacts(customer, plan, membership_facts)

    async def has_reseller_owner_current(self, customer_id: int) -> bool:
        result = await self.uow.execute(
            select(col(ResellerCustomerTable.customer_id))
            .where(col(ResellerCustomerTable.customer_id) == customer_id)
            .with_for_update()
        )
        return result.scalar_one_or_none() is not None


class CheckoutFundingReader:
    """Current owned settlement and balance, without creating wallet rows."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def topup_current(
        self, topup_id: int, customer_id: int
    ) -> TopupModel | None:
        result = await self.uow.execute(
            select(TopupTable)
            .where(
                col(TopupTable.id) == topup_id,
                col(TopupTable.customer_id) == customer_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def balance_current(self, customer_id: int) -> int:
        result = await self.uow.execute(
            select(col(WalletTable.balance_rial))
            .where(col(WalletTable.customer_id) == customer_id)
            .with_for_update()
        )
        balance = result.scalar_one_or_none()
        return balance if balance is not None else 0
