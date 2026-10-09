from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TimestampField,
)


class CheckoutIntentModel(PersistenceEntity):
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    request_key: str = CharField(128, unique=True)
    body_sha256: str = CharField(64)
    purchase_key: str = CharField(128, unique=True)
    plan_id: int = ForeignKeyField("tbl_plans.id")
    revision: int = IntField(default=1)
    state: str = CharField(24)
    funding_mode: str = CharField(24)
    delivery_mode: str = CharField(24)
    price_rial: int = BigIntField()
    offer_sha256: str = CharField(64)
    auto_renew: bool = BoolField()
    expires_at: datetime = TimestampField()
    changed_offer_action: str = CharField(24)
    topup_id: int | None = ForeignKeyField(
        "tbl_topups.id", default=None, unique=True
    )
    subscription_id: int | None = ForeignKeyField(
        "tbl_subscriptions.id", default=None, unique=True
    )
    reason_code: str | None = CharField(64, default=None)
    checked_at: datetime | None = TimestampField(default=None)


class CheckoutActionReceiptModel(PersistenceEntity):
    intent_id: int = ForeignKeyField("tbl_checkout_intents.id", index=True)
    customer_id: int = ForeignKeyField("tbl_customers.id")
    request_key: str = CharField(128, unique=True)
    action: str = CharField(16)
    body_sha256: str = CharField(64)
    accepted_revision: int = IntField()
