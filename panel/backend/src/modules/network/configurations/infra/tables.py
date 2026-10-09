from papilio.infra.db.table import BaseTable
from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field

from src.modules.network.configurations.domain.models import (
    ConfigurationJsonRevisionModel,
    ConfigurationModel,
    InboundPortModel,
    OpenVpnSocketModel,
    ProfileModel,
    SubscriptionLinkModel,
)


class ConfigurationTable(ConfigurationModel, BaseTable, table=True):
    encrypted_settings: str = Field(sa_type=LONGTEXT())
    __table_args__ = (
        UniqueConstraint(
            "node_id", "listen_port", "port_network", name="uq_inbound_bind"
        ),
    )


class ProfileTable(ProfileModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint(
            "configuration_id",
            "subscription_id",
            name="uq_profile_subscription",
        ),
        UniqueConstraint(
            "configuration_id", "client_address", name="uq_profile_address"
        ),
    )


class SubscriptionLinkTable(SubscriptionLinkModel, BaseTable, table=True):
    pass


class InboundPortTable(InboundPortModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint(
            "node_id", "port", "network", name="uq_inbound_socket"
        ),
    )


class OpenVpnSocketTable(OpenVpnSocketModel, BaseTable, table=True):
    path: str = Field(sa_type=String(255, collation="ascii_bin"))
    __table_args__ = (
        UniqueConstraint("node_id", "path", name="uq_openvpn_management"),
    )


class ConfigurationJsonRevisionTable(
    ConfigurationJsonRevisionModel, BaseTable, table=True
):
    encrypted_settings: str = Field(sa_type=LONGTEXT())
    __table_args__ = (
        UniqueConstraint(
            "configuration_id",
            "revision",
            name="uq_configuration_json_revision",
        ),
    )
