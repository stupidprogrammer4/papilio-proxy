from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)


class AutomationRegistrationModel(PersistenceEntity):
    key: str = CharField(32, unique=True)
    revision: int = IntField(default=0)
    policy_json: str = TextField()
    applied_revision: int | None = IntField(default=None)
    registered_at: datetime | None = TimestampField(default=None)


class AutomationRevisionModel(PersistenceEntity):
    key: str = CharField(32, index=True)
    revision: int = IntField()
    policy_json: str = TextField()
    reason: str = CharField(250)
    staff_id: int = ForeignKeyField("tbl_staff.id")
