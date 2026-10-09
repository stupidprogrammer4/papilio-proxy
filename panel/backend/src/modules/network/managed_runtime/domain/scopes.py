from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ManagedProfileScope:
    profile_id: int
    configuration_id: int
    subscription_id: int


@dataclass(frozen=True, slots=True)
class ManagedSubscriptionOwner:
    subscription_id: int
    customer_id: int


@dataclass(frozen=True, slots=True)
class ManagedInstallationScope:
    profiles: tuple[ManagedProfileScope, ...]
    owners: tuple[ManagedSubscriptionOwner, ...]
