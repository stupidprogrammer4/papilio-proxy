from datetime import datetime

from papilio.infra.db.schema.entity import BaseEntity, PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    TimestampField,
)


class StaffModel(PersistenceEntity):
    username: str = CharField(64, unique=True)
    password_hash: str = CharField(256)
    is_active: bool = BoolField(default=True)


class StaffGrantModel(BaseEntity):
    staff_id: int = ForeignKeyField("tbl_staff.id", primary_key=True)
    scope: str = CharField(64, primary_key=True)


class StaffSessionModel(BaseEntity):
    token_hash: str = CharField(64, primary_key=True)
    staff_id: int = ForeignKeyField("tbl_staff.id", index=True)
    csrf_token: str = CharField(64)
    expires_at: datetime = TimestampField(index=True)
