from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class SupportTicketModel(PersistenceEntity):
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    created_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )
    request_key: str = CharField(128)
    subject: str = CharField(100)
    creation_hash: str = CharField(64)
    subscription_id: int | None = ForeignKeyField(
        "tbl_subscriptions.id", default=None
    )
    topup_id: int | None = ForeignKeyField("tbl_topups.id", default=None)
    status: str = CharField(32, index=True)
    revision: int = IntField(default=1)


class SupportMessageModel(PersistenceEntity):
    revision: int = IntField()
    ticket_id: int = ForeignKeyField("tbl_support_tickets.id", index=True)
    request_key: str = CharField(128)
    customer_id: int | None = ForeignKeyField("tbl_customers.id", default=None)
    staff_id: int | None = ForeignKeyField("tbl_staff.id", default=None)
    body: str = TextField()


class SupportStateChangeModel(PersistenceEntity):
    ticket_id: int = ForeignKeyField("tbl_support_tickets.id", index=True)
    revision: int = IntField()
    previous_status: str = CharField(32)
    status: str = CharField(32)
    reason: str = CharField(250)
    customer_id: int | None = ForeignKeyField("tbl_customers.id", default=None)
    staff_id: int | None = ForeignKeyField("tbl_staff.id", default=None)
