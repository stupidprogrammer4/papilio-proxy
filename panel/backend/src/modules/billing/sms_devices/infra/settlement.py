from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import exists, select
from sqlmodel import col

from src.modules.billing.sms.infra.tables import SmsEventTable
from src.modules.billing.sms_devices.domain.settlement import (
    SmsSettlementFacts,
    SmsSettlementOwnerHint,
)
from src.modules.billing.sms_devices.infra.tables import SmsDeviceTable
from src.modules.billing.wallet.infra.tables import TopupTable


class SmsSettlementReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def owner_hints(
        self,
        destination_id: int,
        amount_rial: int,
        topup_since: datetime,
        topup_until: datetime,
        pending_status: str,
        limit: int,
    ) -> list[SmsSettlementOwnerHint]:
        result = await self.uow.execute(
            select(col(TopupTable.id), col(TopupTable.customer_id))
            .where(
                col(TopupTable.destination_id) == destination_id,
                col(TopupTable.amount_rial) == amount_rial,
                col(TopupTable.status) == pending_status,
                col(TopupTable.created_at) >= topup_since,
                col(TopupTable.created_at) <= topup_until,
            )
            .order_by(col(TopupTable.id))
            .limit(limit)
        )
        return [
            SmsSettlementOwnerHint(
                topup_id=row.id, customer_id=row.customer_id
            )
            for row in result.all()
        ]

    async def matches(
        self,
        destination_id: int,
        amount_rial: int,
        topup_since: datetime,
        topup_until: datetime,
        message_since: datetime,
        message_until: datetime,
        pending_status: str,
        settled_status: str,
        approval_mode: str,
        device_active: bool,
        device_valid_at: datetime,
        limit: int,
    ) -> SmsSettlementFacts:
        topups = await self.uow.execute(
            select(TopupTable)
            .where(
                col(TopupTable.destination_id) == destination_id,
                col(TopupTable.amount_rial) == amount_rial,
                col(TopupTable.status) == pending_status,
                col(TopupTable.created_at) >= topup_since,
                col(TopupTable.created_at) <= topup_until,
            )
            .order_by(col(TopupTable.id))
            .limit(limit)
            .with_for_update()
        )
        used = exists(
            select(col(TopupTable.id)).where(
                col(TopupTable.status) == settled_status,
                col(TopupTable.bank_reference)
                == col(SmsEventTable.bank_reference),
            )
        )
        messages = await self.uow.execute(
            select(SmsEventTable)
            .join(
                SmsDeviceTable,
                col(SmsEventTable.device_id) == col(SmsDeviceTable.id),
            )
            .where(
                col(SmsDeviceTable.destination_id) == destination_id,
                col(SmsDeviceTable.approval_mode) == approval_mode,
                col(SmsDeviceTable.is_active) == device_active,
                col(SmsDeviceTable.expires_at) > device_valid_at,
                col(SmsEventTable.amount_rial) == amount_rial,
                col(SmsEventTable.bank_reference).is_not(None),
                col(SmsEventTable.sent_at) >= message_since,
                col(SmsEventTable.sent_at) <= message_until,
                ~used,
            )
            .order_by(col(SmsEventTable.id))
            .limit(limit)
            .with_for_update()
        )
        return SmsSettlementFacts(
            list(topups.scalars().all()), list(messages.scalars().all())
        )

    async def event_ids(
        self,
        destination_id: int,
        amount_rial: int,
        since: datetime,
        until: datetime,
        mode: str,
        active: bool,
        valid_at: datetime,
        limit: int,
    ) -> list[str]:
        result = await self.uow.execute(
            select(col(SmsEventTable.event_id))
            .join(
                SmsDeviceTable,
                col(SmsEventTable.device_id) == col(SmsDeviceTable.id),
            )
            .where(
                col(SmsDeviceTable.destination_id) == destination_id,
                col(SmsDeviceTable.approval_mode) == mode,
                col(SmsDeviceTable.is_active) == active,
                col(SmsDeviceTable.expires_at) > valid_at,
                col(SmsEventTable.amount_rial) == amount_rial,
                col(SmsEventTable.sent_at) >= since,
                col(SmsEventTable.sent_at) <= until,
            )
            .order_by(col(SmsEventTable.id))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def approved_topup_for_event(
        self, event_id: str, device_id: int, approved_status: str
    ) -> int | None:
        canonical_sms = (
            select(col(SmsEventTable.id))
            .where(
                col(SmsEventTable.event_id) == event_id,
                col(SmsEventTable.device_id) == device_id,
            )
            .scalar_subquery()
        )
        # Current owning topup read; immutable SMS provenance is a scalar
        # subquery, so no reversed SMS -> Topup lock sequence is introduced.
        result = await self.uow.execute(
            select(col(TopupTable.id))
            .where(
                col(TopupTable.approved_by_sms_id) == canonical_sms,
                col(TopupTable.approved_by_device_id) == device_id,
                col(TopupTable.status) == approved_status,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()
