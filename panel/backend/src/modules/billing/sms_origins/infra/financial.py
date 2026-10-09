from datetime import datetime
from typing import Literal

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import and_, func, or_, select
from sqlmodel import col

from src.modules.billing.destinations.infra.tables import (
    PaymentDestinationTable,
)
from src.modules.billing.sms_origins.domain.facts import (
    SmsFundingFacts,
    SmsManualBindingHint,
    SmsTopupCandidate,
    SmsTopupHint,
)
from src.modules.billing.sms_origins.infra.tables import (
    ReceivingAliasTable,
    SmsSettlementTable,
)
from src.modules.billing.wallet.infra.tables import TopupTable


class SmsFinancialReader:
    """Declared top-up, destination, and settlement read models."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def owner_hints(
        self,
        amount: int,
        since: datetime,
        until: datetime,
        windows: list[tuple[list[str], Literal["created_at", "updated_at"]]],
        limit: int,
    ) -> list[SmsTopupHint]:
        result = await self.uow.execute(
            select(
                col(TopupTable.id).label("topup_id"),
                col(TopupTable.customer_id),
            )
            .where(
                col(TopupTable.amount_rial) == amount,
                _windows(windows, since, until),
            )
            .order_by(col(TopupTable.id))
            .limit(limit)
        )
        return [SmsTopupHint(**row._mapping) for row in result]

    async def candidates(
        self,
        amount: int,
        since: datetime,
        until: datetime,
        windows: list[tuple[list[str], Literal["created_at", "updated_at"]]],
        limit: int,
    ) -> list[SmsTopupCandidate]:
        topup, destination, settlement = (
            TopupTable,
            PaymentDestinationTable,
            SmsSettlementTable,
        )
        result = await self.uow.execute(
            select(
                col(topup.id),
                col(topup.amount_rial),
                col(topup.customer_id),
                col(topup.status),
                col(topup.destination_id),
                col(topup.receiving_realm_id),
                col(topup.receiving_alias_id),
                col(destination.receiving_alias_id).label(
                    "current_destination_alias_id"
                ),
                col(topup.created_at),
                col(topup.updated_at),
                col(topup.bank_reference),
                col(topup.encrypted_instruction),
                col(settlement.id).label("settlement_id"),
            )
            .select_from(topup)
            .outerjoin(
                destination, col(topup.destination_id) == col(destination.id)
            )
            .outerjoin(settlement, col(settlement.topup_id) == col(topup.id))
            .where(
                col(topup.amount_rial) == amount,
                _windows(windows, since, until),
            )
            .order_by(col(topup.id))
            .limit(limit)
            .with_for_update()
        )
        return [SmsTopupCandidate(**row._mapping) for row in result]

    async def candidate_facts(
        self,
        amount: int,
        since: datetime,
        until: datetime,
        windows: list[tuple[list[str], Literal["created_at", "updated_at"]]],
        limit: int,
    ) -> list[SmsTopupCandidate]:
        topup, destination, settlement = (
            TopupTable,
            PaymentDestinationTable,
            SmsSettlementTable,
        )
        result = await self.uow.execute(
            select(
                col(topup.id),
                col(topup.amount_rial),
                col(topup.customer_id),
                col(topup.status),
                col(topup.destination_id),
                col(topup.receiving_realm_id),
                col(topup.receiving_alias_id),
                col(destination.receiving_alias_id).label(
                    "current_destination_alias_id"
                ),
                col(topup.created_at),
                col(topup.updated_at),
                col(topup.bank_reference),
                col(topup.encrypted_instruction),
                col(settlement.id).label("settlement_id"),
            )
            .select_from(topup)
            .outerjoin(
                destination, col(topup.destination_id) == col(destination.id)
            )
            .outerjoin(settlement, col(settlement.topup_id) == col(topup.id))
            .where(
                col(topup.amount_rial) == amount,
                _windows(windows, since, until),
            )
            .order_by(col(topup.id))
            .limit(limit)
        )
        return [SmsTopupCandidate(**row._mapping) for row in result]

    async def binding_hint(self, id: int) -> SmsManualBindingHint | None:
        topup, destination, alias = (
            TopupTable,
            PaymentDestinationTable,
            ReceivingAliasTable,
        )
        result = await self.uow.execute(
            select(
                col(topup.customer_id),
                col(topup.destination_id),
                col(topup.receiving_realm_id),
                col(topup.receiving_alias_id),
                col(alias.realm_id).label("current_realm_id"),
                col(alias.id).label("current_alias_id"),
            )
            .select_from(topup)
            .outerjoin(
                destination, col(topup.destination_id) == col(destination.id)
            )
            .outerjoin(
                alias, col(destination.receiving_alias_id) == col(alias.id)
            )
            .where(col(topup.id) == id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        captured = row.receiving_realm_id is not None
        return SmsManualBindingHint(
            row.customer_id,
            row.destination_id,
            row.receiving_realm_id if captured else row.current_realm_id,
            row.receiving_alias_id if captured else row.current_alias_id,
            captured,
        )

    async def current_binding(self, id: int) -> SmsManualBindingHint | None:
        topup, destination, alias = (
            TopupTable,
            PaymentDestinationTable,
            ReceivingAliasTable,
        )
        result = await self.uow.execute(
            select(
                col(topup.customer_id),
                col(topup.destination_id),
                col(topup.receiving_realm_id),
                col(topup.receiving_alias_id),
                col(alias.realm_id).label("current_realm_id"),
                col(alias.id).label("current_alias_id"),
            )
            .select_from(topup)
            .outerjoin(
                destination, col(topup.destination_id) == col(destination.id)
            )
            .outerjoin(
                alias, col(destination.receiving_alias_id) == col(alias.id)
            )
            .where(col(topup.id) == id)
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None:
            return None
        captured = row.receiving_realm_id is not None
        return SmsManualBindingHint(
            row.customer_id,
            row.destination_id,
            row.receiving_realm_id if captured else row.current_realm_id,
            row.receiving_alias_id if captured else row.current_alias_id,
            captured,
        )

    async def funding(self, event_id: int) -> SmsFundingFacts | None:
        result = await self.uow.execute(
            select(
                col(TopupTable.id).label("topup_id"),
                col(TopupTable.status).label("topup_status"),
            )
            .select_from(TopupTable)
            .join(
                SmsSettlementTable,
                col(SmsSettlementTable.topup_id) == col(TopupTable.id),
            )
            .where(col(SmsSettlementTable.sms_event_id) == event_id)
            .with_for_update()
        )
        row = result.one_or_none()
        return SmsFundingFacts(**row._mapping) if row is not None else None

    async def utc_now(self) -> datetime:
        result = await self.uow.execute(select(func.utc_timestamp(6)))
        return result.scalar_one()


def _windows(
    windows: list[tuple[list[str], Literal["created_at", "updated_at"]]],
    since: datetime,
    until: datetime,
):
    return or_(
        *[
            and_(
                col(TopupTable.status).in_(states),
                (
                    col(TopupTable.created_at)
                    if field == "created_at"
                    else col(TopupTable.updated_at)
                ).between(since, until),
            )
            for states, field in windows
        ]
    )
