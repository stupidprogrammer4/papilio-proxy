from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from src.modules.network.configurations.domain.models import (
    ConfigurationModel,
    ProfileModel,
)
from src.modules.network.configurations.domain.results import (
    ClientCredentials,
    NodeClientCredentials,
    NodeConfigurationSettings,
    StoredSettings,
)
from src.modules.network.core_runtime.domain.memberships import (
    InstalledProfileMembership,
)
from src.modules.network.nodes.domain.models import NodeModel
from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.sales.catalog.domain.policies import QuotaPolicy
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


@dataclass(frozen=True, slots=True)
class ProvisionTarget:
    configuration: ConfigurationModel
    node: NodeModel


@dataclass(frozen=True, slots=True)
class ProvisionGenerationKey:
    subscription_id: int
    generation: int


@dataclass(frozen=True, slots=True)
class NodeProvisionFacts:
    task: ProvisionTaskModel
    request: ProvisionRequestModel
    subscription: SubscriptionModel
    profile: ProfileModel
    configuration: ConfigurationModel


class NodeClaim(BaseModel):
    credential_sha256: str
    installed_revision_id: int | None = None
    membership_sha256: str | None = None
    membership: InstalledProfileMembership | None = None
    quota_policy: QuotaPolicy
    configuration_revision: int
    listen_port: int
    task_id: int
    request_id: int
    generation: int
    action: str
    claim_token: str
    claim_until: datetime
    core_id: int
    core_kind: str
    configuration_id: int
    profile_id: int
    subscription_id: int
    quota_bytes: int | None
    expires_at: datetime | None
    settings: NodeConfigurationSettings
    credentials: NodeClientCredentials
    client_address: str | None


class ProvisionPayload(BaseModel):
    listen_port: int | None = None
    core_id: int
    settings: StoredSettings
    credentials: ClientCredentials
    client_address: str | None
