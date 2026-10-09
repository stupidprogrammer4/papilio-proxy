from dataclasses import dataclass

from src.modules.network.routing.domain.models import (
    HostGroupModel,
    HostMembershipModel,
    HostModel,
)


@dataclass(frozen=True, slots=True)
class GroupHostFacts:
    host: HostModel
    group: HostGroupModel
    membership: HostMembershipModel
