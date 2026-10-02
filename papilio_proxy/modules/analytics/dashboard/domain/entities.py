from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    users: int
    subscriptions: int
    active: int
    pending: int
    traffic_used: int
    traffic_limit: int
    recent_users: list[tuple[int, str, str | None, int]]
    subscriptions_rows: list[tuple[str, int, str, str, int, int]]
