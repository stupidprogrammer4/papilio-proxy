from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator

from src.modules.accounts.customers.domain.dtos import CustomerAccessState
from src.modules.accounts.resellers.domain.dtos import ResellerDefaults
from src.modules.billing.destinations.domain.dtos import CheckoutPolicy
from src.modules.billing.receipts.domain.dtos import ReceiptPolicy
from src.modules.network.qr_codes.domain.dtos import QrPolicy
from src.modules.operations.notifications.domain.dtos import NotificationPolicy
from src.modules.sales.attention.domain.policies import SubscriptionAlertPolicy
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.checkout.domain.contracts import PurchaseCheckoutPolicy
from src.modules.sales.trials.domain.dtos import TrialPolicy
from src.modules.support.domain.dtos import SupportPolicy


class IpDefaults(BaseDTO):
    enabled: bool | None = None
    mode: Literal["reject_new", "replace_oldest"]
    max_ips: int = Field(gt=0)
    lease_seconds: int = Field(gt=0)
    ban_seconds: int = Field(gt=0)


class BusinessPreferences(BaseDTO):
    purchase_checkout: PurchaseCheckoutPolicy | None = None
    subscription_alerts: SubscriptionAlertPolicy | None = None
    reseller_defaults: ResellerDefaults | None = None
    qr_codes: QrPolicy | None = None
    trials: TrialPolicy | None = None
    notifications: NotificationPolicy | None = None
    support: SupportPolicy | None = None
    customer_creation_access: CustomerAccessState | None = None
    receipts: ReceiptPolicy | None = None
    checkout: CheckoutPolicy | None = None
    quota_policy: QuotaPolicy | None = None
    customer_link_rotation: bool | None = None
    fulfillment: FulfillmentPolicy | None = None
    brand_title: str = Field(min_length=2, max_length=100)
    payment_instructions: str | None = Field(default=None, max_length=4000)
    support_handle: str | None = Field(
        default=None, max_length=100, pattern=r"^@?[A-Za-z0-9_]+$"
    )
    topup_options_rial: list[int] = Field(min_length=1)
    max_plan_duration_days: int = Field(gt=0)
    payment_stale_hours: int = Field(gt=0)
    node_health_stale_seconds: int = Field(gt=0)
    subscription_expiry_warning_hours: int = Field(gt=0)
    provisioning_attention_minutes: int = Field(gt=0)
    ip_defaults: IpDefaults

    @field_validator("topup_options_rial")
    @classmethod
    def valid_amounts(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values) or len(set(values)) != len(
            values
        ):
            raise ValueError(
                "Topup options must be distinct positive rial amounts"
            )
        return values


class PreferencesWrite(BaseDTO):
    expected_revision: int = Field(ge=0)
    values: BusinessPreferences


class PreferencesSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
