from datetime import datetime, timedelta

from src.modules.sales.trials.domain.dtos import TrialPolicy
from src.modules.sales.trials.domain.results import TrialUsage


class TrialEligibility:
    active_statuses = [
        "pending_provision",
        "active",
        "suspended",
        "suspending",
        "resuming",
        "customer_hold",
    ]

    @staticmethod
    def reason(
        policy: TrialPolicy,
        usage: TrialUsage,
        capacity_valid: bool,
        now: datetime,
    ) -> str | None:
        if not policy.enabled:
            return "trial_disabled"
        if not capacity_valid:
            return "trial_capacity"
        if usage.claims >= policy.max_claims_per_customer:
            return "trial_claim_limit"
        if policy.eligibility == "no_paid_purchase" and usage.paid_purchases:
            return "trial_paid_customer"
        if policy.concurrent_mode == "reject_active" and usage.active_claims:
            return "trial_active_exists"
        if (
            usage.latest_claim_at is not None
            and now
            < usage.latest_claim_at
            + timedelta(seconds=policy.cooldown_seconds)
        ):
            return "trial_cooldown"
        return None
