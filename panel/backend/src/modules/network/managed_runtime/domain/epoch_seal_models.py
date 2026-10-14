"""Immutable accepted epoch-seal evidence; no admission or financial writes."""

from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    TextField,
    TimestampField,
)


class ManagedEpochSealModel(PersistenceEntity):
    epoch_id: int = ForeignKeyField("tbl_managed_epoches.id", unique=True)
    request_id: str = CharField(32)
    request_sha256: str = CharField(64)
    receipt_sha256: str = CharField(64)
    acceptance_id: str = CharField(32, unique=True)
    accepted_at: datetime = TimestampField()
    encrypted_receipt: str = TextField()
