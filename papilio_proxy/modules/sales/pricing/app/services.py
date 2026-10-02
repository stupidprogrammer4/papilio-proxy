from __future__ import annotations

from papilio_proxy.modules.sales.pricing.domain.entities import (
    PricingAssumptions,
    PricingProjection,
    PricingValidationError,
)
from papilio_proxy.modules.sales.pricing.interfaces import PricingRepository
from papilio_proxy.modules.sales.subscriptions.domain.entities import Plan

DECIMAL_GB_BYTES = 1_000_000_000
BASIS_POINTS = 10_000
PRICE_STEP_RIAL = 10_000  # 1,000 toman; presentation rounding, not a plan price.


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def validate_pricing(value: PricingAssumptions) -> None:
    if any(
        isinstance(item, bool)
        for item in (
            value.period_days,
            value.daily_server_cost_rial,
            value.included_traffic_gb,
            value.overage_cost_rial_per_gb,
            value.target_customers,
            value.contingency_basis_points,
            value.target_margin_basis_points,
        )
    ):
        raise PricingValidationError("مقادیر قیمت‌گذاری باید عدد صحیح باشند.")
    if not 1 <= value.period_days <= 366:
        raise PricingValidationError("دوره باید بین ۱ و ۳۶۶ روز باشد.")
    if not 0 < value.daily_server_cost_rial <= 10**13 or value.daily_server_cost_rial % 10:
        raise PricingValidationError("هزینهٔ روزانه باید ریالی، مثبت و مضرب ۱۰ باشد.")
    if not 1 <= value.included_traffic_gb <= 10**9:
        raise PricingValidationError("ترافیک همراه سرور باید به گیگابایت اعشاری و مثبت باشد.")
    if not 0 <= value.overage_cost_rial_per_gb <= 10**10 or value.overage_cost_rial_per_gb % 10:
        raise PricingValidationError("هزینهٔ اضافه باید ریالی، نامنفی و مضرب ۱۰ باشد.")
    if not 1 <= value.target_customers <= 100_000:
        raise PricingValidationError("تعداد مشتری هدف باید بین ۱ و ۱۰۰٬۰۰۰ باشد.")
    if not 0 <= value.contingency_basis_points <= 10_000:
        raise PricingValidationError("ذخیرهٔ هزینه باید بین صفر و ۱۰۰ درصد باشد.")
    if not 0 <= value.target_margin_basis_points <= 9_000:
        raise PricingValidationError("حاشیهٔ هدف باید بین صفر و ۹۰ درصد باشد.")


def project_plan(plan: Plan, assumptions: PricingAssumptions) -> PricingProjection:
    """One fully-consuming, single-plan cohort; not a demand or net-profit forecast."""
    validate_pricing(assumptions)
    if plan.duration_days != assumptions.period_days:
        raise PricingValidationError("مدت پلن با دورهٔ مدل قیمت‌گذاری برابر نیست.")
    customers = assumptions.target_customers
    total_bytes = customers * plan.traffic_bytes
    included_bytes = assumptions.included_traffic_gb * DECIMAL_GB_BYTES
    overage_gb = _ceil_div(max(0, total_bytes - included_bytes), DECIMAL_GB_BYTES)
    server_cost = (
        assumptions.daily_server_cost_rial * assumptions.period_days
        + overage_gb * assumptions.overage_cost_rial_per_gb
    )
    buffered_cost = _ceil_div(
        server_cost * (BASIS_POINTS + assumptions.contingency_basis_points), BASIS_POINTS
    )
    revenue = customers * plan.price_rial
    contribution = revenue - buffered_cost
    margin_bps = contribution * BASIS_POINTS // revenue
    required_rial = _ceil_div(
        buffered_cost * BASIS_POINTS,
        customers * (BASIS_POINTS - assumptions.target_margin_basis_points),
    )
    rounded_required = _ceil_div(required_rial, PRICE_STEP_RIAL) * PRICE_STEP_RIAL
    return PricingProjection(
        plan_code=plan.code,
        customers=customers,
        billable_overage_gb=overage_gb,
        revenue_rial=revenue,
        server_cost_rial=server_cost,
        cost_with_contingency_rial=buffered_cost,
        contribution_rial=contribution,
        contribution_margin_basis_points=margin_bps,
        minimum_price_rial_for_target_margin=rounded_required,
    )


class PricingService:
    def __init__(self, repository: PricingRepository) -> None:
        self._repository = repository

    async def get(self) -> PricingAssumptions | None:
        return await self._repository.get()

    async def save(self, value: PricingAssumptions) -> None:
        validate_pricing(value)
        await self._repository.save(value)
