from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)


class CustomerModel(PersistenceEntity):
    service_hold_pending: bool = BoolField(default=False)
    service_hold_revision: int = IntField(default=0)
    services_enabled: bool = BoolField(default=True)
    renewals_enabled: bool = BoolField(default=True)
    service_hold_clock: str | None = CharField(16, default=None)
    service_hold_at: datetime | None = TimestampField(default=None)
    service_hold_reason: str | None = CharField(250, default=None)
    service_hold_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )
    service_hold_by_reseller_account_id: int | None = ForeignKeyField(
        "tbl_reseller_accounts.id", default=None
    )
    telegram_id: int | None = BigIntField(default=None, unique=True)
    display_name: str = CharField(120)
    is_active: bool = BoolField(default=True)


class CustomerAccessChangeModel(PersistenceEntity):
    request_key: str = CharField(128, unique=True)
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    staff_id: int | None = ForeignKeyField("tbl_staff.id", default=None)
    reseller_id: int | None = ForeignKeyField("tbl_resellers.id", default=None)
    actor_account_id: int | None = ForeignKeyField(
        "tbl_reseller_accounts.id", default=None
    )
    previous_json: str = TextField()
    values_json: str = TextField()
    reason: str = CharField(250)
    clock: str | None = CharField(16, default=None)
