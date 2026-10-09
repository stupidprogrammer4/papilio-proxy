from dishka import Provider, Scope, provide

from src.modules.network.ip_limits.app.commands import (
    IpAdmissionCommand,
    IpLimitPolicyCommand,
    IpRestrictionCommand,
)
from src.modules.network.ip_limits.app.leases import IpLeaseTrackingService
from src.modules.network.ip_limits.app.projections import (
    IpPolicyProjectionQuery,
)
from src.modules.network.ip_limits.app.purchased import (
    PurchasedIpPolicyService,
)
from src.modules.network.ip_limits.app.queries import IpLimitQuery
from src.modules.network.ip_limits.infra.clock import IpAdmissionClock
from src.modules.network.ip_limits.infra.leases import IpLeaseStateRepository
from src.modules.network.ip_limits.infra.mysql import (
    IpLimitPolicyRepository,
    IpSessionRepository,
)
from src.modules.network.ip_limits.infra.projections import (
    IpPolicyProjectionReader,
)
from src.modules.network.ip_limits.infra.purchased import (
    PurchasedIpPolicyRepository,
)
from src.modules.network.ip_limits.infra.readers import NodeSubscriptionReader
from src.modules.network.ip_limits.interfaces import (
    IIpAdmissionClock,
    IIpAdmissionCommand,
    IIpLeaseTrackingService,
    IIpLimitPolicyCommand,
    IIpLimitQuery,
    IIpPolicyProjectionQuery,
    IIpRestrictionCommand,
    IPurchasedIpPolicyService,
)


class IpLimitProvider(Provider):
    scope = Scope.REQUEST
    lease_states = provide(IpLeaseStateRepository)
    lease_tracking = provide(
        IpLeaseTrackingService, provides=IIpLeaseTrackingService
    )
    policies = provide(IpLimitPolicyRepository)
    sessions = provide(IpSessionRepository)
    assignments = provide(NodeSubscriptionReader)
    clock = provide(IpAdmissionClock, provides=IIpAdmissionClock)
    purchased_repo = provide(PurchasedIpPolicyRepository)
    purchased_service = provide(
        PurchasedIpPolicyService, provides=IPurchasedIpPolicyService
    )
    projection_reader = provide(IpPolicyProjectionReader)
    projection_query = provide(
        IpPolicyProjectionQuery, provides=IIpPolicyProjectionQuery
    )
    policy_command = provide(
        IpLimitPolicyCommand, provides=IIpLimitPolicyCommand
    )
    admission_command = provide(
        IpAdmissionCommand, provides=IIpAdmissionCommand
    )
    restriction_command = provide(
        IpRestrictionCommand, provides=IIpRestrictionCommand
    )
    query = provide(IpLimitQuery, provides=IIpLimitQuery)
