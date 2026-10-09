from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TimestampField,
)


class NodeModel(PersistenceEntity):
    code: str = CharField(64, unique=True)
    label: str = CharField(100)
    public_host: str = CharField(255)
    public_port: int = IntField()
    protocol: str = CharField(32)
    agent_key_hash: str = CharField(64)
    is_enabled: bool = BoolField(default=False)


class ProbeModel(PersistenceEntity):
    event_id: str = CharField(128, unique=True)
    node_id: int = ForeignKeyField("tbl_nodes.id", index=True)
    client_network: str = CharField(64, index=True)
    latency_ms: int | None = IntField(default=None)
    success: bool = BoolField()
    sampled_at: datetime = TimestampField(index=True)
