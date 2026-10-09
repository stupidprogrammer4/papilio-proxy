from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class PlanModel(PersistenceEntity):
    quota_policy_json: str | None = TextField(default=None)
    fulfillment_json: str | None = TextField(default=None)
    ip_limit_json: str | None = TextField(default=None)
    group_id: int | None = ForeignKeyField("tbl_host_groups.id", default=None)
    code: str = CharField(64, unique=True)
    title: str = CharField(100)
    quota_bytes: int | None = BigIntField(default=None)
    duration_days: int | None = IntField(default=None)
    price_rial: int = BigIntField()
    sort_order: int = IntField(default=0)
    is_active: bool = BoolField(default=False)
