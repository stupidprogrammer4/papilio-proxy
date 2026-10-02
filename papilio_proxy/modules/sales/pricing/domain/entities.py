from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PricingAssumptions:
    period_days: int
    daily_server_cost_rial: int
    included_traffic_gb: int
    overage_cost_rial_per_gb: int
    target_customers: int
    contingency_basis_points: int
    target_margin_basis_points: int


@dataclass(frozen=True, slots=True)
class PricingProjection:
    plan_code: str
    customers: int
    billable_overage_gb: int
    revenue_rial: int
    server_cost_rial: int
    cost_with_contingency_rial: int
    contribution_rial: int
    contribution_margin_basis_points: int
    minimum_price_rial_for_target_margin: int


class PricingValidationError(ValueError):
    """An owner-editable cost assumption is outside supported bounds."""
