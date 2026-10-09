from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.billing.destinations.infra.tables import (
    PaymentDestinationTable,
)
from src.modules.billing.sms_devices.infra.tables import SmsDeviceTable
from src.modules.billing.sms_origins.domain.facts import SmsIntakeFacts
from src.modules.billing.sms_origins.infra.tables import (
    ReceivingAliasTable,
    ReceivingRealmTable,
    SmsParserProfileTable,
    SmsParserRevisionTable,
)


class SmsIntakeReader:
    """Capture source/device, receiving binding and parser revision.

    This read does not authorize settlement; current financial locks do that.
    """

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def get(self, device_id: int) -> SmsIntakeFacts | None:
        device, destination, alias, realm = (
            SmsDeviceTable,
            PaymentDestinationTable,
            ReceivingAliasTable,
            ReceivingRealmTable,
        )
        profile, revision = SmsParserProfileTable, SmsParserRevisionTable
        result = await self.uow.execute(
            select(
                col(device.senders_json).label("enrolled_senders_json"),
                col(device.id).label("device_id"),
                col(destination.id).label("destination_id"),
                col(destination.revision).label("destination_revision"),
                col(alias.id).label("alias_id"),
                col(realm.id).label("realm_id"),
                col(realm.realm_key),
                col(revision.id).label("parser_revision_id"),
                col(revision.definition_json).label("parser_definition_json"),
                col(revision.definition_sha256).label(
                    "parser_definition_sha256"
                ),
            )
            .select_from(device)
            .outerjoin(
                destination, col(device.destination_id) == col(destination.id)
            )
            .outerjoin(
                alias, col(destination.receiving_alias_id) == col(alias.id)
            )
            .outerjoin(realm, col(alias.realm_id) == col(realm.id))
            .outerjoin(
                profile, col(device.parser_profile_id) == col(profile.id)
            )
            .outerjoin(
                revision,
                (col(revision.profile_id) == col(profile.id))
                & (col(revision.revision) == col(profile.revision)),
            )
            .where(col(device.id) == device_id)
        )
        row = result.one_or_none()
        return SmsIntakeFacts(**row._mapping) if row is not None else None
