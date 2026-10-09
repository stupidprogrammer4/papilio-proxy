from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    TimestampField,
)


class SubscriptionAttentionModel(PersistenceEntity):
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", unique=True)
    status: str = CharField(32)
    wallet_balance_rial: int = BigIntField()
    payer_customer_id: int | None = ForeignKeyField(
        "tbl_customers.id", default=None, index=True
    )
    renewal_price_rial: int | None = BigIntField(default=None)
    renewal_available: bool | None = BoolField(default=None)
    checked_at: datetime = TimestampField(index=True)
