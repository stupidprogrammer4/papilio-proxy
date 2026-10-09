from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
)


class HostModel(PersistenceEntity):
    configuration_id: int = ForeignKeyField(
        "tbl_configurations.id", index=True
    )
    label: str = CharField(100)
    address: str = CharField(255)
    port: int = IntField()
    is_enabled: bool = BoolField()


class HostGroupModel(PersistenceEntity):
    code: str = CharField(64, unique=True)
    title: str = CharField(100)
    is_enabled: bool = BoolField()


class HostMembershipModel(PersistenceEntity):
    group_id: int = ForeignKeyField("tbl_host_groups.id", index=True)
    host_id: int = ForeignKeyField("tbl_hosts.id", index=True)
    label: str | None = CharField(100, default=None)
    address: str | None = CharField(255, default=None)
    port: int | None = IntField(default=None)
    server_name: str | None = CharField(253, default=None)
    is_enabled: bool = BoolField()
    sort_order: int = IntField()
