from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.network.configurations.domain.dtos import ConfigurationOptions
from src.modules.network.configurations.domain.models import (
    ConfigurationModel,
    ProfileModel,
)
from src.modules.network.configurations.domain.openvpn import (
    OpenVpnCertificate,
    OpenVpnClientCertificate,
    OpenVpnPkiMaterial,
    OpenVpnServerMaterial,
)
from src.modules.network.configurations.domain.server_json import (
    ServerJsonDocument,
)
from src.modules.network.cores.domain.models import CoreModel
from src.modules.network.nodes.domain.models import NodeModel
from src.modules.network.routing.domain.models import (
    HostGroupModel,
    HostMembershipModel,
    HostModel,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


class ConfigurationSettingsFields(BaseModel):
    server_json: ServerJsonDocument | None = None
    options: ConfigurationOptions
    private_key: str | None = None
    public_key: str | None = None
    short_id: str | None = None
    server_password: str | None = None


class StoredSettings(ConfigurationSettingsFields):
    openvpn: OpenVpnPkiMaterial | None = None


class NodeConfigurationSettings(ConfigurationSettingsFields):
    openvpn: OpenVpnServerMaterial | None = None


class ClientCredentialFields(BaseModel):
    identity: str
    password: str | None = None
    private_key: str | None = None
    public_key: str | None = None
    preshared_key: str | None = None


class ClientCredentials(ClientCredentialFields):
    openvpn: OpenVpnClientCertificate | None = None


class NodeClientCredentials(ClientCredentialFields):
    openvpn: OpenVpnCertificate | None = None


@dataclass(frozen=True, slots=True)
class ProfileAppliedUpdate:
    profile_id: int
    generation: int | None
    revision: int | None


@dataclass(frozen=True, slots=True)
class SubscriptionURL:
    subscription_id: int
    url: str


@dataclass(frozen=True, slots=True)
class SubscriptionTokenInput:
    subscription_id: int
    token: str


@dataclass(frozen=True, slots=True)
class SubscriptionLinkMaterial:
    subscription_id: int
    token: str
    token_hash: str
    encrypted_token: str


@dataclass(frozen=True, slots=True)
class ProfileFacts:
    customer: CustomerModel
    profile: ProfileModel
    subscription: SubscriptionModel
    request_state: str | None = None


@dataclass(frozen=True, slots=True)
class SubscriptionConfigurationFacts:
    customer: CustomerModel
    profile: ProfileModel
    subscription: SubscriptionModel
    configuration: ConfigurationModel
    node: NodeModel
    host: HostModel | None
    group: HostGroupModel | None
    membership: HostMembershipModel | None

    def detached(self) -> "SubscriptionConfigurationFacts":
        return SubscriptionConfigurationFacts(
            customer=CustomerModel.model_validate(self.customer.model_dump()),
            profile=ProfileModel.model_validate(self.profile.model_dump()),
            subscription=SubscriptionModel.model_validate(
                self.subscription.model_dump()
            ),
            configuration=ConfigurationModel.model_validate(
                self.configuration.model_dump()
            ),
            node=NodeModel.model_validate(self.node.model_dump()),
            host=None
            if self.host is None
            else HostModel.model_validate(self.host.model_dump()),
            group=None
            if self.group is None
            else HostGroupModel.model_validate(self.group.model_dump()),
            membership=None
            if self.membership is None
            else HostMembershipModel.model_validate(
                self.membership.model_dump()
            ),
        )


@dataclass(frozen=True, slots=True)
class ConfigurationDownload:
    filename: str
    content: str
    media_type: str


@dataclass(frozen=True, slots=True)
class ConfigurationBundle:
    configuration: ConfigurationModel
    node: NodeModel
    settings: StoredSettings
    profiles: list[ProfileFacts]


@dataclass(frozen=True, slots=True)
class ConnectionEndpoint:
    id: int
    public_host: str
    public_port: int


class PublicSubscription(BaseModel):
    qr_enabled: bool = False
    feed_url: str | None
    id: int
    status: str
    quota_bytes: int | None
    used_bytes: int
    expires_at: datetime | None
    auto_renew: bool
    brand_title: str
    support_handle: str | None

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )


class PublicProfile(BaseModel):
    profile_id: int
    host_id: int | None
    label: str
    protocol: str


@dataclass(frozen=True, slots=True)
class ConfigurationServerFacts:
    configuration: ConfigurationModel
    node: NodeModel
    core: CoreModel


@dataclass(frozen=True, slots=True)
class ConfigurationServerExport:
    configuration_id: int
    revision: int
    download: ConfigurationDownload


@dataclass(frozen=True, slots=True)
class ServerProfileInput:
    profile_id: int
    configuration_id: int
    services_available: bool
    status: str
    expires_at: datetime | None
    quota_bytes: int | None
    used_bytes: int
    encrypted_credentials: str
    client_address: str | None
    request_state: str | None = None
    generation: int = 0


@dataclass(frozen=True, slots=True)
class ServerConfigurationInput:
    endpoint: ConnectionEndpoint
    revision: int
    core_kind: str
    protocol: str
    encrypted_settings: str
