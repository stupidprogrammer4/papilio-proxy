from dataclasses import dataclass

from papilio.api.requests.queries import BaseQuery
from pydantic import BaseModel, Field

from src.modules.network.configurations.domain.models import ConfigurationModel
from src.modules.network.nodes.domain.models import NodeModel
from src.modules.network.routing.domain.models import (
    HostGroupModel,
    HostMembershipModel,
    HostModel,
)


@dataclass(frozen=True, slots=True)
class PlanConfigurationFacts:
    configuration: ConfigurationModel
    node: NodeModel
    host: HostModel
    group: HostGroupModel
    membership: HostMembershipModel


class PlanConfigurationSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class PlanConfigurationRead(BaseModel):
    configuration_id: int
    node_id: int
    node_label: str
    label: str
    protocol: str
    host_id: int
    group_id: int
    is_enabled: bool
