from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    IntField,
    TimestampField,
)


class ReceiptOcrOutboxModel(PersistenceEntity):
    receipt_id: int = ForeignKeyField("tbl_payment_receipts.id", unique=True)
    status: str = CharField(16, default="pending", index=True)
    attempts: int = IntField(default=0)
    claim_token: str | None = CharField(64, default=None)
    lease_until: datetime | None = TimestampField(default=None, index=True)
    published_at: datetime | None = TimestampField(default=None)
