from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class CustomerTierModel(PersistenceEntity):
    code: str = CharField(32, unique=True)
    title: str = CharField(100)
    minimum_bytes: int = BigIntField()
    discount_bps: int = IntField(default=0)
    is_enabled: bool = BoolField(default=True)
    revision: int = IntField(default=1)


class LoyaltyPolicyModel(PersistenceEntity):
    code: str = CharField(32, unique=True)
    values_json: str = TextField()
    revision: int = IntField(default=1)


class PurchaseVolumeModel(PersistenceEntity):
    reference: str = CharField(128, unique=True)
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", index=True)
    generation: int = IntField()
    volume_bytes: int = BigIntField()
    purchase_count: int = IntField()
    paid_rial: int = BigIntField()
    commerce_json: str | None = TextField(default=None)
    reverses_id: int | None = ForeignKeyField(
        "tbl_purchase_volumes.id", default=None, unique=True
    )
