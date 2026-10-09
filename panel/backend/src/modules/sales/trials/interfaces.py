from collections.abc import Awaitable
from typing import Protocol

from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.trials.domain.dtos import TrialClaim, TrialPolicy
from src.modules.sales.trials.domain.results import TrialAvailability


class ITrialPolicyQuery(Protocol):
    def current(self) -> Awaitable[TrialPolicy]: ...
    def capacity_valid(self, policy: TrialPolicy) -> bool: ...


class ITrialQuery(Protocol):
    def availability(
        self, customer_id: int
    ) -> Awaitable[TrialAvailability]: ...


class ITrialCommand(Protocol):
    def claim(
        self, customer_id: int, data: TrialClaim
    ) -> Awaitable[SubscriptionModel]: ...
