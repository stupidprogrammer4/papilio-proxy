import ipaddress
from math import ceil
from typing import Literal
from urllib.parse import urlsplit

from papilio.core.config import Settings
from papilio_tasks.apps.taskiq import RedisSettings
from pydantic import BaseModel, Field, SecretStr, model_validator

from src.modules.accounts.customers.domain.dtos import CustomerAccessState
from src.modules.accounts.resellers.domain.dtos import ResellerDefaults
from src.modules.billing.destinations.domain.dtos import CheckoutPolicy
from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentIdentifierCapacity,
)
from src.modules.billing.sms_origins.domain.contracts import SmsOriginCapacity
from src.modules.network.configurations.domain.openvpn import OpenVpnCapacity
from src.modules.network.configurations.domain.server_json import (
    ServerJsonCapacity,
)
from src.modules.network.core_runtime.domain.dtos import RuntimeCapacity
from src.modules.network.core_runtime.domain.memberships import (
    CoreProvisioningCapacity,
)
from src.modules.network.core_runtime.domain.usage import CoreUsageCapacity
from src.modules.network.cores.domain.exports import CoreExportCapacity
from src.modules.network.managed_runtime.domain.installations import (
    ManagedAdapterPolicy,
)
from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityCapacity,
)
from src.modules.network.qr_codes.domain.dtos import QrPolicy
from src.modules.operations.automation.domain.dtos import ScheduleMode
from src.modules.operations.notifications.domain.dtos import NotificationPolicy
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.checkout.domain.contracts import CheckoutCapacity
from src.modules.sales.loyalty.domain.dtos import (
    CustomerTierWrite,
    LoyaltyPolicy,
)
from src.modules.sales.trials.domain.dtos import TrialPolicy
from src.modules.support.domain.dtos import SupportPolicy


class SecuritySettings(BaseModel):
    admin_session_key: str = Field(min_length=32)
    sms_webhook_key: str = Field(min_length=32)
    bot_service_key: str = Field(min_length=32)


class PublicSettings(BaseModel):
    customer_portal_origin: str
    customer_link_rotation: bool
    brand_title: str = Field(min_length=2, max_length=100)
    subscription_origin: str
    admin_origin: str
    additional_admin_origins: list[str] = Field(default_factory=list)
    payment_instructions: str | None = None
    support_handle: str | None = None


class TaskSettings(BaseModel):
    scheduler: RedisSettings


class EventsSettings(BaseModel):
    nats_url: str = Field(min_length=1)


class IpLimitSettings(BaseModel):
    transition_mode: Literal["drain_leases", "require_closed_receipts"] = (
        "drain_leases"
    )
    # Legacy configurations retain their existing export profile capacity.
    max_assignment_profiles: int | None = Field(default=None, gt=0)
    enabled: bool
    mode: Literal["reject_new", "replace_oldest"]
    max_ips: int = Field(gt=0)
    lease_seconds: int = Field(gt=0)
    ban_seconds: int = Field(gt=0)
    max_ips_ceiling: int = Field(gt=0)
    max_lease_seconds: int = Field(gt=0)
    max_ban_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_defaults(self) -> "IpLimitSettings":
        if (
            self.max_ips > self.max_ips_ceiling
            or self.lease_seconds > self.max_lease_seconds
            or self.ban_seconds > self.max_ban_seconds
        ):
            raise ValueError("IP limit defaults exceed configured ceilings")
        return self


class OperationsSettings(BaseModel):
    @model_validator(mode="after")
    def valid_automation_capacity(self) -> "OperationsSettings":
        if (
            self.automation_min_interval_seconds
            > self.automation_max_interval_seconds
        ):
            raise ValueError("Automation interval bounds are reversed")
        if (
            self.automation_default_mode == ScheduleMode.INTERVAL
            and not self.automation_min_interval_seconds
            <= self.automation_default_interval_seconds
            <= self.automation_max_interval_seconds
        ):
            raise ValueError("Default interval exceeds configured capacity")
        return self

    automation_default_mode: ScheduleMode
    automation_default_interval_seconds: int = Field(gt=0)
    automation_min_interval_seconds: int = Field(gt=0)
    automation_max_interval_seconds: int = Field(gt=0)
    automation_enabled: bool
    automation_timezone: str = Field(min_length=1)
    automation_registration_cron: str = Field(min_length=1)
    automation_registration_prefix: str = Field(min_length=1)
    automation_max_batch_size: int = Field(gt=0)
    automation_max_recheck_seconds: int = Field(gt=0)
    customer_hold_batch_size: int = Field(gt=0)
    customer_hold_scan_cron: str = Field(min_length=1)
    max_staff_grants: int = Field(gt=0)
    max_staff_roles: int = Field(gt=0)
    max_staff_role_members: int = Field(gt=0)
    staff_inactive_role_assignment: bool
    lifecycle_scan_cron: str = Field(min_length=1)
    lifecycle_batch_size: int = Field(gt=0)
    max_business_topup_options: int = Field(gt=0)
    max_request_body_bytes: int = Field(gt=0)
    configuration_export_max_profiles: int = Field(gt=0)
    admin_page_size: int = Field(gt=0)
    admin_page_size_max: int = Field(gt=0)
    max_plan_duration_days: int = Field(gt=0)
    renewal_batch_size: int = Field(gt=0)
    renewal_scan_cron: str = Field(min_length=1)
    payment_scan_cron: str = Field(min_length=1)
    payment_batch_size: int = Field(gt=0)
    payment_recheck_seconds: int = Field(gt=0)
    payment_stale_hours: int = Field(gt=0)
    node_health_scan_cron: str = Field(min_length=1)
    node_health_batch_size: int = Field(gt=0)
    node_health_recheck_seconds: int = Field(gt=0)
    node_health_stale_seconds: int = Field(gt=0)
    subscription_attention_scan_cron: str = Field(min_length=1)
    subscription_attention_batch_size: int = Field(gt=0)
    subscription_attention_recheck_seconds: int = Field(gt=0)
    subscription_expiry_warning_hours: int = Field(gt=0)
    provisioning_attention_minutes: int = Field(gt=0)
    automation_retry_attempts: int = Field(gt=0)
    automation_retry_delay_seconds: float = Field(ge=0)
    bot_page_size: int = Field(gt=0)
    quality_window_minutes: int = Field(gt=0)
    quality_min_samples: int = Field(gt=0)
    quality_min_success_ratio: float = Field(gt=0, le=1)
    sms_clock_skew_seconds: int = Field(gt=0)
    sms_match_window_hours: int = Field(gt=0)
    sms_match_before_topup_minutes: int = Field(ge=0)
    staff_session_hours: int = Field(gt=0)
    bot_topup_options_rial: list[int] = Field(min_length=1)


class FulfillmentSettings(BaseModel):
    policy: FulfillmentPolicy
    scan_cron: str = Field(min_length=1)
    batch_size: int = Field(gt=0)
    recheck_seconds: int = Field(gt=0)
    max_targets: int = Field(gt=0)
    max_address_scan: int = Field(gt=0)
    max_claim_seconds: int = Field(gt=0)
    max_attempts: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_policy(self) -> "FulfillmentSettings":
        if (
            self.policy.claim_seconds > self.max_claim_seconds
            or self.policy.max_attempts > self.max_attempts
            or self.policy.minimum_successes > self.max_targets
        ):
            raise ValueError(
                "Fulfillment policy exceeds configured capacities"
            )
        return self


class UsageSettings(BaseModel):
    policy: QuotaPolicy
    max_grant_bytes: int = Field(gt=0)
    max_grant_seconds: int = Field(gt=0)
    max_report_delta_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_policy(self) -> "UsageSettings":
        if (
            self.policy.grant_bytes > self.max_grant_bytes
            or self.policy.grant_seconds > self.max_grant_seconds
        ):
            raise ValueError("Quota policy exceeds configured capacities")
        return self


class CheckoutSettings(BaseModel):
    payment_identifier_capacity: PaymentIdentifierCapacity | None = None
    policy: CheckoutPolicy
    maximum_topup_rial: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_policy(self) -> "CheckoutSettings":
        identifier = self.policy.payment_identifier
        capacity = self.payment_identifier_capacity
        if (
            identifier is not None
            and identifier.mode == "rial_suffix4"
            and (
                capacity is None
                or identifier.max_adjustment_rial
                > capacity.max_adjustment_rial
                or identifier.max_adjustment_rial
                // identifier.amount_step_rial
                + 1
                > capacity.max_candidate_amounts
            )
        ):
            raise ValueError(
                "Payment identifier policy exceeds configured capacity"
            )
        if self.policy.maximum_topup_rial > self.maximum_topup_rial:
            raise ValueError("Checkout policy exceeds configured capacity")
        return self


class CustomerAuthSettings(BaseModel):
    enabled: bool
    login_seconds: int = Field(gt=0)
    session_seconds: int = Field(gt=0)


class ReceiptSettings(BaseModel):
    max_concurrent_images: int = Field(gt=0)
    enabled: bool
    max_image_bytes: int = Field(gt=0)
    max_request_bytes: int = Field(gt=0)
    max_per_topup: int = Field(gt=0)
    max_pixels: int = Field(gt=0)
    allowed_formats: list[Literal["JPEG", "PNG", "WEBP"]] = Field(min_length=1)
    jpeg_quality: int = Field(ge=1, le=95)
    ocr_api_key: SecretStr | None = None
    ocr_timeout_seconds: int = Field(default=20, gt=0, le=120)

    @model_validator(mode="after")
    def valid_upload(self) -> "ReceiptSettings":
        if self.max_request_bytes <= self.max_image_bytes:
            raise ValueError(
                "Receipt request budget must include multipart overhead"
            )
        return self


class CustomerSettings(BaseModel):
    creation_access: CustomerAccessState


class SupportSettings(BaseModel):
    policy: SupportPolicy
    max_open_tickets: int = Field(gt=0)
    max_messages_per_ticket: int = Field(gt=0)
    max_message_chars: int = Field(gt=0, le=16383)

    @model_validator(mode="after")
    def valid_defaults(self) -> "SupportSettings":
        if (
            self.policy.max_open_tickets > self.max_open_tickets
            or self.policy.max_messages_per_ticket
            > self.max_messages_per_ticket
            or self.policy.max_message_chars > self.max_message_chars
        ):
            raise ValueError("Support defaults exceed owning capacities")
        return self


class NotificationHttpPoolSettings(BaseModel):
    max_connections: int = Field(gt=0)
    max_connections_per_host: int = Field(gt=0)
    keepalive_seconds: float = Field(gt=0)
    dns_cache_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def bounded_host_capacity(self) -> "NotificationHttpPoolSettings":
        if self.max_connections_per_host > self.max_connections:
            raise ValueError("Host capacity exceeds the connection pool")
        return self


class NotificationSettings(BaseModel):
    policy: NotificationPolicy
    outbound_enabled: bool
    endpoint: str | None
    delivery_key: str | None = Field(min_length=32)
    allow_loopback_http: bool
    timeout_seconds: float = Field(gt=0)
    max_response_bytes: int = Field(gt=0)
    lease_margin_seconds: int = Field(gt=0)
    max_attempts: int = Field(gt=0)
    max_retry_seconds: int = Field(gt=0)
    max_lease_seconds: int = Field(gt=0)
    max_message_chars: int = Field(gt=0, le=16383)
    batch_size: int = Field(gt=0)
    scan_cron: str = Field(min_length=9)
    http_pool: NotificationHttpPoolSettings | None = None

    def transport_pool(self) -> NotificationHttpPoolSettings:
        if self.http_pool is not None:
            return self.http_pool
        return NotificationHttpPoolSettings(
            max_connections=self.batch_size,
            max_connections_per_host=self.batch_size,
            keepalive_seconds=self.timeout_seconds,
            dns_cache_seconds=ceil(self.timeout_seconds),
        )

    @model_validator(mode="after")
    def valid_defaults(self) -> "NotificationSettings":
        if (
            self.policy.max_attempts > self.max_attempts
            or self.policy.max_retry_seconds > self.max_retry_seconds
            or self.policy.lease_seconds > self.max_lease_seconds
            or self.policy.lease_seconds
            <= self.timeout_seconds + self.lease_margin_seconds
            or self.policy.max_message_chars > self.max_message_chars
        ):
            raise ValueError("Notification defaults exceed owning capacities")
        if self.delivery_key is not None and not self.delivery_key.isascii():
            raise ValueError("The delivery key must contain ASCII characters")
        if self.outbound_enabled and (
            not self.endpoint
            or not self.delivery_key
            or len(self.delivery_key) < 32
        ):
            raise ValueError(
                "Outbound delivery requires a private endpoint and key"
            )
        if self.endpoint:
            parsed = urlsplit(self.endpoint)
            loopback = False
            try:
                loopback = ipaddress.ip_address(
                    parsed.hostname or ""
                ).is_loopback
            except ValueError:
                pass
            if (
                parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.query
                or not parsed.hostname
                or parsed.scheme not in {"http", "https"}
                or parsed.scheme == "http"
                and not (self.allow_loopback_http and loopback)
            ):
                raise ValueError(
                    "Use HTTPS or explicitly permitted literal loopback HTTP"
                )
        return self


class TrialSettings(BaseModel):
    policy: TrialPolicy
    max_claims_per_customer: int = Field(gt=0)
    max_cooldown_seconds: int = Field(ge=0)
    max_quota_bytes: int = Field(gt=0, le=9223372036854775807)
    max_duration_days: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_defaults(self) -> "TrialSettings":
        if (
            self.policy.max_claims_per_customer > self.max_claims_per_customer
            or self.policy.cooldown_seconds > self.max_cooldown_seconds
            or self.policy.quota_bytes > self.max_quota_bytes
            or self.policy.duration_days > self.max_duration_days
        ):
            raise ValueError("Trial defaults exceed owning capacities")
        return self


class QrSettings(BaseModel):
    policy: QrPolicy
    max_box_size: int = Field(gt=0)
    max_border_modules: int = Field(ge=4)
    max_side_pixels: int = Field(gt=0)
    max_payload_bytes: int = Field(gt=0)
    max_png_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_policy(self) -> "QrSettings":
        if (
            self.policy.box_size > self.max_box_size
            or self.policy.border_modules > self.max_border_modules
        ):
            raise ValueError("QR defaults exceed owning capacities")
        return self


class ResellerSettings(BaseModel):
    enabled: bool
    portal_origin: str
    session_seconds: int = Field(gt=0)
    max_customers_per_reseller: int = Field(gt=0)
    max_accounts_per_reseller: int = Field(gt=0)
    max_plans_per_reseller: int = Field(gt=0)
    max_sessions_per_account: int = Field(gt=0)
    max_scopes_per_account: int = Field(gt=0)
    defaults: ResellerDefaults

    @model_validator(mode="after")
    def valid_defaults(self) -> "ResellerSettings":
        parsed = urlsplit(self.portal_origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or not self.portal_origin.isascii()
        ):
            raise ValueError("Reseller portal must be an explicit origin")
        self.portal_origin = self.portal_origin.rstrip("/")
        policy = self.defaults.policy
        if (
            policy.customer_capacity > self.max_customers_per_reseller
            or policy.account_capacity > self.max_accounts_per_reseller
            or policy.plan_capacity > self.max_plans_per_reseller
            or policy.max_sessions_per_account > self.max_sessions_per_account
            or len(self.defaults.owner_access.scopes)
            > self.max_scopes_per_account
        ):
            raise ValueError("Reseller defaults exceed owning capacities")
        return self


class SmsDeviceSettings(BaseModel):
    max_match_candidates: int = Field(gt=0)
    enabled: bool
    max_senders_per_device: int = Field(gt=0)
    max_key_validity_days: int = Field(gt=0)
    status_stale_after_seconds: int = Field(default=3600, gt=0)


class LoyaltySettings(BaseModel):
    max_plan_overrides: int = Field(gt=0)
    max_tiers: int = Field(gt=0)
    defaults: LoyaltyPolicy
    initial_tiers: list[CustomerTierWrite]


class SubscriptionAlertCapacity(BaseModel):
    max_expiry_hours: int = Field(default=87600, gt=0, le=8760000)
    max_low_quota_rules: int = Field(default=16, gt=0)
    max_expiry_rules: int = Field(default=16, gt=0)


class PapilioSettings(Settings):
    managed_adapter: "ManagedAdapterPolicy | None" = None
    subscription_alerts_capacity: SubscriptionAlertCapacity = Field(
        default_factory=SubscriptionAlertCapacity
    )
    core_provisioning: CoreProvisioningCapacity | None = None
    core_runtime: RuntimeCapacity | None = None
    core_usage: CoreUsageCapacity | None = None
    node_capabilities: NodeCapabilityCapacity | None = None
    core_exports: CoreExportCapacity | None = None
    loyalty: LoyaltySettings | None = None
    sms_devices: SmsDeviceSettings | None = None
    sms_origins: SmsOriginCapacity | None = None
    configuration_json: ServerJsonCapacity | None = None
    openvpn: OpenVpnCapacity | None = None
    resellers: ResellerSettings | None = None
    qr_codes: QrSettings | None = None
    trials: TrialSettings
    notifications: NotificationSettings
    support: SupportSettings
    customers: CustomerSettings
    receipts: ReceiptSettings
    customer_auth: CustomerAuthSettings
    security: SecuritySettings
    public: PublicSettings
    tasks: TaskSettings
    events: EventsSettings = Field(
        default_factory=lambda: EventsSettings(nats_url="nats://nats:4222")
    )
    operations: OperationsSettings
    ip_limits: IpLimitSettings
    checkout: CheckoutSettings
    purchase_intents: CheckoutCapacity | None = None
    usage: UsageSettings
    fulfillment: FulfillmentSettings

    @model_validator(mode="after")
    def validate_crypto(self) -> "PapilioSettings":
        if self.crypto is None or len(self.crypto.encryption_key) < 32:
            raise ValueError(
                "Configure crypto.encryption_key with at least 32 characters"
            )
        return self

    @property
    def configuration_encryption_key(self) -> str:
        if self.crypto is None:
            raise RuntimeError("Missing validated crypto settings")
        return self.crypto.encryption_key
