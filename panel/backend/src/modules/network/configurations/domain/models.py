from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class ConfigurationModel(PersistenceEntity):
    revision: int = IntField(default=1)
    node_id: int = ForeignKeyField("tbl_nodes.id", index=True)
    core_id: int = ForeignKeyField("tbl_cores.id", index=True)
    listen_port: int = IntField()
    port_network: str = CharField(4)
    label: str = CharField(100)
    protocol: str = CharField(32)
    encrypted_settings: str = TextField()


class ProfileModel(PersistenceEntity):
    applied_revision: int | None = IntField(default=None)
    applied_generation: int | None = IntField(default=None)
    configuration_id: int = ForeignKeyField(
        "tbl_configurations.id", index=True
    )
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", index=True)
    client_address: str | None = CharField(64, default=None)
    encrypted_credentials: str = TextField()


class SubscriptionLinkModel(PersistenceEntity):
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", unique=True)
    token_hash: str = CharField(64, unique=True)
    encrypted_token: str = TextField()


class InboundPortModel(PersistenceEntity):
    configuration_id: int = ForeignKeyField(
        "tbl_configurations.id", index=True
    )
    node_id: int = ForeignKeyField("tbl_nodes.id")
    port: int = IntField()
    network: str = CharField(3)


class OpenVpnSocketModel(PersistenceEntity):
    configuration_id: int = ForeignKeyField(
        "tbl_configurations.id", unique=True
    )
    node_id: int = ForeignKeyField("tbl_nodes.id")
    path: str = CharField(255)


class ConfigurationJsonRevisionModel(PersistenceEntity):
    configuration_id: int = ForeignKeyField(
        "tbl_configurations.id", index=True
    )
    revision: int = IntField()
    staff_id: int = ForeignKeyField("tbl_staff.id")
    reason: str = CharField(250)
    encrypted_settings: str = TextField()
