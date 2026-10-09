from typing import get_args

from papilio.errors.exceptions import ConflictException, ValidationException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.app.policies import ResellerCapacity
from src.modules.billing.payment_identifiers.domain.contracts import (
    RIAL_SUFFIX_MODULUS,
    PaymentIdentifierCapabilities,
)
from src.modules.billing.receipts.domain.dtos import ReceiptPolicy
from src.modules.network.qr_codes.app.policies import QrCapacity
from src.modules.operations.notifications.domain.dtos import NotificationKind
from src.modules.operations.preferences.domain.dtos import (
    BusinessPreferences,
    IpDefaults,
    PreferencesSearch,
    PreferencesWrite,
)
from src.modules.operations.preferences.domain.models import (
    PreferencesRevisionModel,
)
from src.modules.operations.preferences.domain.results import (
    PreferencesCapabilities,
    PreferencesSnapshot,
)
from src.modules.operations.preferences.infra.mysql import (
    PreferencesRepository,
)
from src.modules.sales.checkout.domain.contracts import TransientConflictAction


class PreferencesService:
    def __init__(
        self, repo: PreferencesRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    def capabilities(self) -> PreferencesCapabilities:
        return PreferencesCapabilities(
            payment_identifiers=PaymentIdentifierCapabilities(
                capacity=self.settings.checkout.payment_identifier_capacity,
                supported_modes=["exact_requested", "rial_suffix4"],
                suffix_digits=4,
                suffix_modulus=RIAL_SUFFIX_MODULUS,
            ),
            supported_notification_kinds=list(NotificationKind),
            checkout_transient_conflict_modes=list(
                get_args(TransientConflictAction)
            ),
        )

    @property
    def receipt_defaults(self) -> ReceiptPolicy:
        return ReceiptPolicy(
            enabled=self.settings.receipts.enabled,
            max_per_topup=self.settings.receipts.max_per_topup,
            allowed_formats=self.settings.receipts.allowed_formats,
        )

    async def current(self, *, locked: bool = False) -> PreferencesSnapshot:
        row = await self.repo.latest(locked=locked)
        if row is not None:
            values = BusinessPreferences.model_validate_json(row.values_json)
            if (
                values.reseller_defaults is None
                and self.settings.resellers is not None
            ):
                values.reseller_defaults = self.settings.resellers.defaults
            if values.qr_codes is None and self.settings.qr_codes is not None:
                values.qr_codes = self.settings.qr_codes.policy
            if values.trials is None:
                values.trials = self.settings.trials.policy
            if values.notifications is None:
                values.notifications = self.settings.notifications.policy
            if values.support is None:
                values.support = self.settings.support.policy
            if values.customer_link_rotation is None:
                values.customer_link_rotation = (
                    self.settings.public.customer_link_rotation
                )
            if values.customer_creation_access is None:
                values.customer_creation_access = (
                    self.settings.customers.creation_access
                )
            if values.receipts is None:
                values.receipts = self.receipt_defaults
            if values.checkout is None:
                values.checkout = self.settings.checkout.policy
            if values.quota_policy is None:
                values.quota_policy = self.settings.usage.policy
            if values.fulfillment is None:
                values.fulfillment = self.settings.fulfillment.policy
            if values.ip_defaults.enabled is None:
                values.ip_defaults.enabled = self.settings.ip_limits.enabled
            return PreferencesSnapshot(
                capabilities=self.capabilities(),
                revision=row.revision,
                values=values,
            )
        policy = self.settings.operations
        return PreferencesSnapshot(
            capabilities=self.capabilities(),
            revision=0,
            values=BusinessPreferences(
                reseller_defaults=self.settings.resellers.defaults
                if self.settings.resellers is not None
                else None,
                qr_codes=self.settings.qr_codes.policy
                if self.settings.qr_codes is not None
                else None,
                trials=self.settings.trials.policy,
                notifications=self.settings.notifications.policy,
                support=self.settings.support.policy,
                customer_creation_access=self.settings.customers.creation_access,
                customer_link_rotation=self.settings.public.customer_link_rotation,
                checkout=self.settings.checkout.policy,
                receipts=self.receipt_defaults,
                quota_policy=self.settings.usage.policy,
                fulfillment=self.settings.fulfillment.policy,
                brand_title=self.settings.public.brand_title,
                payment_instructions=self.settings.public.payment_instructions,
                support_handle=self.settings.public.support_handle,
                topup_options_rial=policy.bot_topup_options_rial,
                max_plan_duration_days=policy.max_plan_duration_days,
                payment_stale_hours=policy.payment_stale_hours,
                node_health_stale_seconds=policy.node_health_stale_seconds,
                subscription_expiry_warning_hours=policy.subscription_expiry_warning_hours,
                provisioning_attention_minutes=policy.provisioning_attention_minutes,
                ip_defaults=IpDefaults.model_validate(
                    self.settings.ip_limits.model_dump()
                ),
            ),
        )

    @handle_conflicts(message_code="preferences_revision_conflict")
    @transactional
    async def write(
        self, data: PreferencesWrite, staff_id: int
    ) -> PreferencesSnapshot:
        current = await self.current()
        if current.revision != data.expected_revision:
            raise ConflictException(
                message="تنظیمات تغییر کرده‌اند؛ نسخهٔ تازه را دریافت کنید.",
                message_code="preferences_revision_conflict",
                unique_dict={"revision": current.revision},
            )
        checkout_policy = data.values.purchase_checkout
        capacity = self.settings.purchase_intents
        if checkout_policy is not None and checkout_policy.enabled:
            if (
                capacity is None
                or not capacity.minimum_expiry_seconds
                <= checkout_policy.default_expiry_seconds
                <= capacity.maximum_expiry_seconds
            ):
                raise ValidationException(
                    message="Checkout policy exceeds configured capacity",
                    message_code="purchase_checkout_capacity",
                    loc=["values", "purchase_checkout"],
                    input=None,
                )
        qr = data.values.qr_codes or current.values.qr_codes
        defaults = (
            data.values.reseller_defaults or current.values.reseller_defaults
        )
        if defaults is not None and any(defaults.access.model_dump().values()):
            reseller_capacity = ResellerCapacity.configured(self.settings)
            ResellerCapacity.validate(defaults.policy, reseller_capacity)
            ResellerCapacity.scopes(defaults.owner_access, reseller_capacity)
        data.values.reseller_defaults = defaults
        if (
            qr is not None
            and qr.enabled
            and not QrCapacity.valid(qr, self.settings.qr_codes)
        ):
            raise ValidationException(
                message="سیاست کد تصویری از ظرفیت عملیاتی بیشتر است.",
                message_code="qr_policy_capacity",
                loc=["values", "qr_codes"],
                input=qr.model_dump(),
            )
        data.values.qr_codes = qr
        if data.values.customer_creation_access is None:
            data.values.customer_creation_access = (
                current.values.customer_creation_access
            )
        maximum = self.settings.operations.max_business_topup_options
        if data.values.customer_link_rotation is None:
            data.values.customer_link_rotation = (
                current.values.customer_link_rotation
            )
        if len(data.values.topup_options_rial) > maximum:
            raise ValidationException(
                message="تعداد مبلغ‌های پیشنهادی بیش از ظرفیت تنظیم‌شده است.",
                message_code="preferences_topup_capacity",
                loc=["values", "topup_options_rial"],
                input=len(data.values.topup_options_rial),
                ctx={"maximum": maximum},
            )
        limits = self.settings.ip_limits
        fulfillment = (
            data.values.fulfillment
            or current.values.fulfillment
            or self.settings.fulfillment.policy
        )
        capacity = self.settings.fulfillment
        if (
            fulfillment.claim_seconds > capacity.max_claim_seconds
            or fulfillment.max_attempts > capacity.max_attempts
            or fulfillment.minimum_successes > capacity.max_targets
        ):
            raise ValidationException(
                message="سیاست تحویل از سقف عملیاتی بیشتر است.",
                message_code="fulfillment_capacity",
                loc=["values", "fulfillment"],
                input=fulfillment.model_dump(),
                ctx={},
            )
        quota = (
            data.values.quota_policy
            or current.values.quota_policy
            or self.settings.usage.policy
        )
        if (
            quota.grant_bytes > self.settings.usage.max_grant_bytes
            or quota.grant_seconds > self.settings.usage.max_grant_seconds
        ):
            raise ValidationException(
                message="سیاست سهمیه از سقف عملیاتی بیشتر است.",
                message_code="usage_grant_capacity",
                loc=["values", "quota_policy"],
                input=quota.model_dump(),
                ctx={},
            )
        checkout = (
            data.values.checkout
            or current.values.checkout
            or self.settings.checkout.policy
        )
        if (
            checkout.maximum_topup_rial
            > self.settings.checkout.maximum_topup_rial
        ):
            raise ValidationException(
                message="سقف پرداخت از ظرفیت عملیاتی بیشتر است.",
                message_code="checkout_capacity",
                loc=["values", "checkout"],
                input=checkout.model_dump(),
                ctx={},
            )
        identifier = checkout.payment_identifier
        identifier_capacity = (
            self.settings.checkout.payment_identifier_capacity
        )
        if (
            identifier is not None
            and identifier.mode == "rial_suffix4"
            and (
                identifier_capacity is None
                or identifier.max_adjustment_rial
                > identifier_capacity.max_adjustment_rial
                or identifier.max_adjustment_rial
                // identifier.amount_step_rial
                + 1
                > identifier_capacity.max_candidate_amounts
            )
        ):
            raise ValidationException(
                message=(
                    "Payment identifier policy exceeds configured capacity."
                ),
                message_code="payment_identifier_capacity",
                loc=["values", "checkout", "payment_identifier"],
                input=identifier.model_dump(),
                ctx={},
            )
        receipts = (
            data.values.receipts
            or current.values.receipts
            or self.receipt_defaults
        )
        receipt_capacity = self.settings.receipts
        if (
            receipts.max_per_topup > receipt_capacity.max_per_topup
            or not set(receipts.allowed_formats)
            <= set(receipt_capacity.allowed_formats)
            or (receipts.enabled and not receipt_capacity.enabled)
        ):
            raise ValidationException(
                message="سیاست رسید از سقف عملیاتی بیشتر است.",
                message_code="receipt_policy_capacity",
                loc=["values", "receipts"],
                input=receipts.model_dump(),
                ctx={},
            )
        trials = (
            data.values.trials
            or current.values.trials
            or self.settings.trials.policy
        )
        tc = self.settings.trials
        if (
            trials.max_claims_per_customer > tc.max_claims_per_customer
            or trials.cooldown_seconds > tc.max_cooldown_seconds
            or trials.quota_bytes > tc.max_quota_bytes
            or trials.duration_days > tc.max_duration_days
        ):
            raise ValidationException(
                message="سیاست آزمایشی از ظرفیت عملیاتی بیشتر است.",
                message_code="trial_capacity",
                loc=["values", "trials"],
                input=trials.model_dump(),
            )
        data.values.trials = trials
        notifications = (
            data.values.notifications
            or current.values.notifications
            or self.settings.notifications.policy
        )
        nc = self.settings.notifications
        if (
            notifications.max_attempts > nc.max_attempts
            or notifications.max_retry_seconds > nc.max_retry_seconds
            or notifications.lease_seconds > nc.max_lease_seconds
            or notifications.lease_seconds
            <= nc.timeout_seconds + nc.lease_margin_seconds
            or notifications.max_message_chars > nc.max_message_chars
        ):
            raise ValidationException(
                message="سیاست اعلان از ظرفیت عملیاتی بیشتر است.",
                message_code="notification_policy_capacity",
                loc=["values", "notifications"],
                input=notifications.model_dump(),
            )
        data.values.notifications = notifications
        alerts = data.values.subscription_alerts
        capacity = self.settings.subscription_alerts_capacity
        if alerts is not None and (
            len(alerts.low_quota) > capacity.max_low_quota_rules
            or len(alerts.expiry_hours) > capacity.max_expiry_rules
            or any(
                value > capacity.max_expiry_hours
                for value in alerts.expiry_hours
            )
        ):
            raise ValidationException(
                message="Alert policy exceeds configured capacity",
                message_code="subscription_alert_capacity",
                loc=["values", "subscription_alerts"],
                input=alerts.model_dump(),
            )
        support = (
            data.values.support
            or current.values.support
            or self.settings.support.policy
        )
        support_capacity = self.settings.support
        if (
            support.max_open_tickets > support_capacity.max_open_tickets
            or support.max_messages_per_ticket
            > support_capacity.max_messages_per_ticket
            or support.max_message_chars > support_capacity.max_message_chars
        ):
            raise ValidationException(
                message="سیاست پشتیبانی از ظرفیت تنظیم‌شده بیشتر است.",
                message_code="support_policy_capacity",
                loc=["values", "support"],
                input=support.model_dump(),
                ctx={},
            )
        data.values.support = support
        data.values.receipts = receipts
        data.values.checkout = checkout
        data.values.quota_policy = quota
        data.values.fulfillment = fulfillment
        policy = data.values.ip_defaults
        if policy.enabled is None:
            policy.enabled = current.values.ip_defaults.enabled
        if (
            policy.max_ips > limits.max_ips_ceiling
            or policy.lease_seconds > limits.max_lease_seconds
            or policy.ban_seconds > limits.max_ban_seconds
        ):
            raise ValidationException(
                message="مقادیر سیاست از سقف عملیاتی بیشتر است.",
                message_code="ip_policy_capacity",
                loc=["values", "ip_defaults"],
                input=policy.model_dump(),
                ctx={},
            )
        row = await self.repo.create(
            PreferencesRevisionModel(
                revision=current.revision + 1,
                values_json=data.values.model_dump_json(),
                changed_by_staff_id=staff_id,
            )
        )
        return PreferencesSnapshot(
            capabilities=self.capabilities(),
            revision=row.revision,
            values=data.values,
        )

    async def history(
        self, data: PreferencesSearch
    ) -> ServicePage[PreferencesRevisionModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page((data.page - 1) * limit, limit)
        return service_page(result, limit)
