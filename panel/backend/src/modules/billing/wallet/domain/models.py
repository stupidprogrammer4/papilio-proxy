from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class WalletModel(PersistenceEntity):
    customer_id: int = ForeignKeyField("tbl_customers.id", unique=True)
    balance_rial: int = BigIntField(default=0)


class WalletEntryModel(PersistenceEntity):
    wallet_id: int = ForeignKeyField("tbl_wallets.id", index=True)
    amount_rial: int = BigIntField()
    balance_after_rial: int = BigIntField()
    reference: str = CharField(128, unique=True)
    reason: str = CharField(32)


class TopupModel(PersistenceEntity):
    requested_amount_rial: int | None = BigIntField(default=None)
    payment_identifier_mode: str = CharField(24, default="exact_requested")
    payment_identifier_code4: str | None = CharField(4, default=None)
    approved_by_device_id: int | None = ForeignKeyField(
        "tbl_sms_devices.id", default=None
    )
    approved_by_sms_id: int | None = ForeignKeyField(
        "tbl_sms_events.id", default=None, unique=True
    )
    request_key: str | None = CharField(128, default=None, unique=True)
    destination_id: int | None = ForeignKeyField(
        "tbl_payment_destinations.id", default=None
    )
    encrypted_instruction: str | None = TextField(default=None)
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    amount_rial: int = BigIntField()
    status: str = CharField(16, default="pending")
    revision: int = IntField(default=1)
    bank_reference: str | None = CharField(128, default=None, unique=True)
    approved_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )

    receiving_realm_id: int | None = ForeignKeyField(
        "tbl_receiving_realms.id", default=None
    )
    receiving_alias_id: int | None = ForeignKeyField(
        "tbl_receiving_aliases.id", default=None
    )
    captured_destination_revision: int | None = IntField(default=None)
