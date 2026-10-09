from datetime import datetime

from papilio.infra.db.schema.entity import BaseEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    TimestampField,
)


class CustomerLoginModel(BaseEntity):
    token_hash: str = CharField(64, primary_key=True)
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    expires_at: datetime = TimestampField(index=True)


class CustomerSessionModel(BaseEntity):
    token_hash: str = CharField(64, primary_key=True)
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    csrf_token: str = CharField(64)
    expires_at: datetime = TimestampField(index=True)
