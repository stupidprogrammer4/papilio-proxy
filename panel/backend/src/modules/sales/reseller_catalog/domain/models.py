from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class ResellerPlanModel(PersistenceEntity):
    reseller_id: int = ForeignKeyField("tbl_resellers.id", index=True)
    plan_id: int = ForeignKeyField("tbl_plans.id")
    enabled: bool = BoolField()
    revision: int = IntField(default=1)
    price_json: str = TextField()


class ResellerPlanChangeModel(PersistenceEntity):
    agreement_id: int = ForeignKeyField("tbl_reseller_plans.id", index=True)
    staff_id: int = ForeignKeyField("tbl_staff.id")
    revision: int = IntField()
    enabled: bool = BoolField()
    price_json: str = TextField()
    reason: str = CharField(250)
