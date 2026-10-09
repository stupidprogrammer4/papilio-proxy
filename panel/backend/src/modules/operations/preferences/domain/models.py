from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import ForeignKeyField, IntField, TextField


class PreferencesRevisionModel(PersistenceEntity):
    revision: int = IntField(unique=True)
    values_json: str = TextField()
    changed_by_staff_id: int = ForeignKeyField("tbl_staff.id")
