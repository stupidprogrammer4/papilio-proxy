from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    TextField,
    TimestampField,
)


class NodeCapabilityObservationModel(PersistenceEntity):
    node_id: int = ForeignKeyField("tbl_nodes.id", index=True)
    report_id: str = CharField(32)
    report_sha256: str = CharField(64)
    normalized_report: str = TextField()
    observed_at: datetime = TimestampField(index=True)
    received_at: datetime = TimestampField(index=True)
