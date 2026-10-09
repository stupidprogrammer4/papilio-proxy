from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class BalancerPolicyModel(PersistenceEntity):
    group_id: int = ForeignKeyField("tbl_host_groups.id")
    client_core: str = CharField(16)
    revision: int = IntField(default=1)
    policy_json: str = TextField()
