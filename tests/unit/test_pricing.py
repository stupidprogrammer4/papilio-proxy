from __future__ import annotations

from unittest import TestCase

from papilio_proxy.modules.sales.pricing.app.services import project_plan, validate_pricing
from papilio_proxy.modules.sales.pricing.domain.entities import (
    PricingAssumptions,
    PricingValidationError,
)
from papilio_proxy.modules.sales.subscriptions.domain.entities import Plan


class PricingTests(TestCase):
    def setUp(self) -> None:
        self.assumptions = PricingAssumptions(
            period_days=30,
            daily_server_cost_rial=800_000,
            included_traffic_gb=900,
            overage_cost_rial_per_gb=3_500,
            target_customers=25,
            contingency_basis_points=1_000,
            target_margin_basis_points=2_500,
        )

    def test_30_gib_plan_stays_under_decimal_provider_quota(self) -> None:
        plan = Plan("M30", "۳۰ گیگ", 30, 30, 1_490_000)
        result = project_plan(plan, self.assumptions)
        self.assertEqual(result.billable_overage_gb, 0)
        self.assertEqual(result.server_cost_rial, 24_000_000)
        self.assertEqual(result.cost_with_contingency_rial, 26_400_000)
        self.assertEqual(result.contribution_rial, 10_850_000)
        self.assertEqual(result.minimum_price_rial_for_target_margin, 1_410_000)

    def test_100_gib_plan_bills_whole_decimal_gigabytes(self) -> None:
        plan = Plan("M100", "۱۰۰ گیگ", 100, 30, 2_190_000)
        result = project_plan(plan, self.assumptions)
        self.assertEqual(result.billable_overage_gb, 1_785)
        self.assertEqual(result.server_cost_rial, 30_247_500)
        self.assertEqual(result.cost_with_contingency_rial, 33_272_250)
        self.assertEqual(result.contribution_rial, 21_477_750)
        self.assertEqual(result.minimum_price_rial_for_target_margin, 1_780_000)

    def test_cost_assumptions_are_validated_and_duration_must_match(self) -> None:
        validate_pricing(self.assumptions)
        with self.assertRaises(PricingValidationError):
            validate_pricing(PricingAssumptions(30, 800_000, 900, 3_500, 0, 1_000, 2_500))
        with self.assertRaises(PricingValidationError):
            project_plan(Plan("M", "دو ماهه", 30, 60, 1_490_000), self.assumptions)
