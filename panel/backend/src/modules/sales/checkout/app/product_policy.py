import hashlib
import json

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.operations.preferences.domain.dtos import BusinessPreferences
from src.modules.sales.checkout.app.errors import checkout_conflict
from src.modules.sales.checkout.domain.contracts import (
    CheckoutCapacity,
    PurchaseCheckoutPolicy,
)
from src.modules.sales.checkout.domain.facts import (
    CheckoutFingerprintInput,
    CheckoutOfferFacts,
)
from src.modules.sales.loyalty.domain.results import CustomerPriceQuote


class CheckoutProductPolicy:
    @staticmethod
    def offer_terms(
        data: CheckoutFingerprintInput,
    ) -> tuple[str, IpLimitChoice]:
        """Hash and displayed IP terms share a detached snapshot."""
        ip_policy = (
            IpLimitChoice.model_validate_json(data.ip_limit_json)
            if data.ip_limit_json
            else IpLimitChoice.model_validate(
                data.ip_limit_default.model_dump()
            )
        )
        return CheckoutProductPolicy.fingerprint(data), ip_policy

    @staticmethod
    def admit(
        facts: CheckoutOfferFacts,
        capacity: CheckoutCapacity,
        policy: PurchaseCheckoutPolicy,
    ) -> None:
        if not policy.enabled:
            raise checkout_conflict("checkout_disabled", facts.plan.id)
        if (
            not facts.customer.is_active
            or not CustomerAccessPolicy.services_available(facts.customer)
        ):
            raise checkout_conflict("customer_inactive", facts.plan.id)
        if not facts.plan.is_active:
            raise checkout_conflict("plan_inactive", facts.plan.id)
        if len(facts.memberships) > capacity.max_offer_memberships:
            raise checkout_conflict("checkout_offer_capacity", facts.plan.id)
        if facts.plan.group_id is None:
            if policy.admission_mode != "allow_manual_profiles":
                raise checkout_conflict(
                    "checkout_bundle_required", facts.plan.id
                )
        elif not facts.memberships or not any(
            row.is_available for row in facts.memberships
        ):
            raise checkout_conflict(
                "checkout_bundle_unavailable", facts.plan.id
            )

    @staticmethod
    def computation_input(
        facts: CheckoutOfferFacts,
        quote: CustomerPriceQuote,
        values: BusinessPreferences,
        settings: PapilioSettings,
    ) -> CheckoutFingerprintInput:
        """Capture scalar facts and detached policies on the owning loop."""
        return CheckoutFingerprintInput(
            plan_id=facts.plan.id,
            group_id=facts.plan.group_id,
            quota_bytes=facts.plan.quota_bytes,
            duration_days=facts.plan.duration_days,
            price_rial=quote.price_rial,
            fulfillment_json=facts.plan.fulfillment_json,
            quota_policy_json=facts.plan.quota_policy_json,
            ip_limit_json=facts.plan.ip_limit_json,
            fulfillment_default=(
                values.fulfillment or settings.fulfillment.policy
            ).model_copy(deep=True),
            quota_default=(
                values.quota_policy or settings.usage.policy
            ).model_copy(deep=True),
            ip_limit_default=values.ip_defaults.model_copy(deep=True),
            configurations=tuple(
                (row.configuration_id, row.protocol)
                for row in facts.memberships
                if row.is_selected
            ),
        )

    @staticmethod
    def fingerprint(data: CheckoutFingerprintInput) -> str:
        defaults = {
            "fulfillment": json.loads(data.fulfillment_json)
            if data.fulfillment_json
            else data.fulfillment_default.model_dump(mode="json"),
            "quota": json.loads(data.quota_policy_json)
            if data.quota_policy_json
            else data.quota_default.model_dump(mode="json"),
            "ip_limit": json.loads(data.ip_limit_json)
            if data.ip_limit_json
            else data.ip_limit_default.model_dump(mode="json"),
        }
        payload = {
            "plan_id": data.plan_id,
            "group_id": data.group_id,
            "quota_bytes": data.quota_bytes,
            "duration_days": data.duration_days,
            "price_rial": data.price_rial,
            "effective_policies": defaults,
            "configurations": sorted(set(data.configurations)),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
