from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    CharField,
    ForeignKeyField,
    IntField,
    TimestampField,
)


class SmsEventModel(PersistenceEntity):
    device_id: int | None = ForeignKeyField(
        "tbl_sms_devices.id", default=None, index=True
    )
    event_id: str = CharField(128, unique=True)
    sender: str = CharField(100)
    text_digest: str = CharField(64)
    amount_rial: int | None = BigIntField(default=None)
    bank_reference: str | None = CharField(128, default=None)
    sent_at: datetime = TimestampField()

    parser_revision_id: int | None = ForeignKeyField(
        "tbl_sms_parser_revisions.id", default=None
    )
    receiving_realm_id: int | None = ForeignKeyField(
        "tbl_receiving_realms.id", default=None
    )
    receiving_alias_id: int | None = ForeignKeyField(
        "tbl_receiving_aliases.id", default=None
    )
    captured_destination_id: int | None = ForeignKeyField(
        "tbl_payment_destinations.id", default=None
    )
    captured_destination_revision: int | None = IntField(default=None)
    direction: str | None = CharField(12, default=None)
    parse_reason_code: str | None = CharField(64, default=None)
    balance_rial: int | None = BigIntField(default=None)
    original_provider_timestamp_ms: int | None = BigIntField(default=None)
    origin_kind: str | None = CharField(24, default=None)
    original_sender: str | None = CharField(100, default=None)
    canonicalization_revision: int | None = IntField(default=None)
    canonical_message_digest: str | None = CharField(64, default=None)
    origin_identity_sha256: str | None = CharField(64, default=None)
    parser_definition_sha256: str | None = CharField(64, default=None)

    origin_reason_code: str | None = CharField(64, default=None)

    declared_notification_sha256: str | None = CharField(64, default=None)
