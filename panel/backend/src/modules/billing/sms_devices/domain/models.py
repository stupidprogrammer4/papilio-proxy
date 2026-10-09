from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)


class SmsDeviceModel(PersistenceEntity):
    approval_mode: str = CharField(16, default="manual")
    destination_id: int | None = ForeignKeyField(
        "tbl_payment_destinations.id", default=None
    )
    label: str = CharField(100)
    encrypted_key: str = TextField()
    senders_json: str = TextField()
    is_active: bool = BoolField(default=True)
    revision: int = IntField(default=1)
    expires_at: datetime = TimestampField()

    parser_profile_id: int | None = ForeignKeyField(
        "tbl_sms_parser_profiles.id", default=None
    )
    settlement_identity_mode: str = CharField(
        32, default="bank_reference_required"
    )
