from dataclasses import dataclass
from datetime import datetime

from papilio.api.requests.queries import BaseQuery
from pydantic import BaseModel, Field

from src.modules.network.configurations.domain.models import (
    ConfigurationModel,
    ProfileModel,
)
from src.modules.network.nodes.domain.models import NodeModel
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


@dataclass(frozen=True, slots=True)
class CustomerConfigurationFacts:
    profile: ProfileModel
    subscription: SubscriptionModel
    plan: PlanModel
    configuration: ConfigurationModel
    node: NodeModel


class CustomerConfigurationSearch(BaseQuery):
    subscription_id: int | None = Field(default=None, gt=0)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class CustomerConfigurationRead(BaseModel):
    profile_id: int
    subscription_id: int
    customer_id: int
    plan_id: int
    plan_title: str
    configuration_id: int
    configuration_label: str
    node_id: int
    node_label: str
    protocol: str
    status: str
    desired_revision: int
    applied_revision: int | None
    quota_bytes: int | None
    used_bytes: int
    expires_at: datetime | None
    auto_renew: bool
