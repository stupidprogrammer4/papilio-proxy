from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import ForeignKeyField, IntField
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field


class PreferencesRevisionModel(PersistenceEntity):
    revision: int = IntField(unique=True)
    values_json: str = Field(sa_type=LONGTEXT())
    changed_by_staff_id: int = ForeignKeyField("tbl_staff.id")
