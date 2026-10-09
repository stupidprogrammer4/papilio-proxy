from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    IntField,
    TimestampField,
)


class NodeHealthModel(PersistenceEntity):
    node_id: int = ForeignKeyField("tbl_nodes.id", unique=True)
    status: str = CharField(32)
    sample_count: int = IntField()
    successful_count: int = IntField()
    average_latency_ms: int | None = IntField(default=None)
    last_sample_at: datetime | None = TimestampField(default=None)
    checked_at: datetime = TimestampField(index=True)
