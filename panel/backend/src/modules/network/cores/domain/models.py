from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import CharField, ForeignKeyField


class CoreModel(PersistenceEntity):
    node_id: int = ForeignKeyField("tbl_nodes.id", index=True)
    code: str = CharField(64)
    label: str = CharField(100)
    kind: str = CharField(32)
