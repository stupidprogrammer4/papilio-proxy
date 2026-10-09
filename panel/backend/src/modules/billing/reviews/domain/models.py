from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    IntField,
    TimestampField,
)


class PaymentReviewModel(PersistenceEntity):
    topup_id: int = ForeignKeyField("tbl_topups.id", unique=True)
    status: str = CharField(32)
    candidate_count: int = IntField()
    competing_topup_count: int = IntField()
    checked_at: datetime = TimestampField(index=True)
