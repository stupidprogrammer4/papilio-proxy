from datetime import UTC, datetime

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.ip_limits.domain.dtos import (
    IpSessionCriteria,
    IpSessionSearch,
)
from src.modules.network.ip_limits.domain.models import IpSessionModel
from src.modules.network.ip_limits.domain.purchased import (
    IpTransitionModeRead,
    IpTransitionOptionsRead,
)
from src.modules.network.ip_limits.domain.results import IpLimitDetail
from src.modules.network.ip_limits.infra.mysql import (
    IpLimitPolicyRepository,
    IpSessionRepository,
)
from src.modules.network.ip_limits.interfaces import IIpPolicyProjectionQuery
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand


class IpLimitQuery:
    def __init__(
        self,
        subscriptions: ISubscriptionCommand,
        policies: IpLimitPolicyRepository,
        sessions: IpSessionRepository,
        settings: PapilioSettings,
        preferences: IPreferencesService,
        projection: IIpPolicyProjectionQuery,
    ) -> None:
        self.subscriptions = subscriptions
        self.policies = policies
        self.session_repo = sessions
        self.settings = settings
        self.preferences = preferences
        self.projection = projection

    async def detail(self, subscription_id: int) -> IpLimitDetail:
        await self.subscriptions.get(subscription_id)
        policy = await self.policies.by_subscription(subscription_id)
        preferences = (await self.preferences.current()).values
        defaults = self.settings.ip_limits.model_copy(
            update=preferences.ip_defaults.model_dump()
        )
        projection = await self.projection.single(subscription_id)
        return IpLimitDetail(
            subscription_id,
            policy,
            defaults,
            projection.purchased_ip_policy,
            projection.effective_ip_policy,
            IpTransitionOptionsRead(
                default_mode=defaults.transition_mode,
                choices=[
                    IpTransitionModeRead(
                        mode="drain_leases", available=True, reason=None
                    ),
                    IpTransitionModeRead(
                        mode="require_closed_receipts",
                        available=False,
                        reason="closed_receipts_unavailable",
                    ),
                ],
            ),
        )

    async def sessions(
        self, subscription_id: int, data: IpSessionSearch
    ) -> ServicePage[IpSessionModel]:
        await self.subscriptions.get(subscription_id)
        limit = page_size(self.settings, data.per_page)
        now = datetime.now(UTC).replace(tzinfo=None)
        criteria = IpSessionCriteria(
            source_ip_query=data.q,
            expires_after=now if data.state == "active" else None,
            expires_at_or_before=now if data.state == "inactive" else None,
            blocked_after=now if data.state == "blocked" else None,
            unblocked_at_or_before=now
            if data.state in {"active", "inactive"}
            else None,
        )
        result = await self.session_repo.page(
            subscription_id,
            criteria,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)
