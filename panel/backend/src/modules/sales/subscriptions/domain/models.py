from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)


class SubscriptionModel(PersistenceEntity):
    payer_customer_id: int | None = ForeignKeyField(
        "tbl_customers.id", default=None, index=True
    )
    reseller_id: int | None = ForeignKeyField(
        "tbl_resellers.id", default=None, index=True
    )
    reseller_agreement_id: int | None = ForeignKeyField(
        "tbl_reseller_plans.id", default=None
    )
    reseller_billing_json: str | None = TextField(default=None)
    commerce_json: str | None = TextField(default=None)
    entitlement_kind: str = CharField(16, default="paid")
    trial_policy_json: str | None = TextField(default=None)
    suspended_at: datetime | None = TimestampField(default=None)
    suspension_clock: str | None = CharField(16, default=None)
    suspension_reason: str | None = CharField(250, default=None)
    suspended_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )
    suspended_by_reseller_account_id: int | None = ForeignKeyField(
        "tbl_reseller_accounts.id", default=None
    )
    lifecycle_checked_at: datetime | None = TimestampField(default=None)
    quota_policy_json: str | None = TextField(default=None)
    fulfillment_json: str | None = TextField(default=None)
    provisioning_managed: bool = BoolField(default=False)
    used_bytes: int = BigIntField(default=0)
    base_quota_bytes: int | None = BigIntField(default=None)
    activated_at: datetime | None = TimestampField(default=None)
    group_id: int | None = ForeignKeyField("tbl_host_groups.id", default=None)
    purchase_key: str = CharField(128, unique=True)
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    plan_id: int = ForeignKeyField("tbl_plans.id")
    quota_bytes: int | None = BigIntField(default=None)
    price_rial: int = BigIntField()
    duration_days: int | None = IntField(default=None)
    expires_at: datetime | None = TimestampField(default=None, index=True)
    status: str = CharField(32, default="pending_provision")
    auto_renew: bool = BoolField(default=False)
    renewal_count: int = IntField(default=0)
    renewal_checked_at: datetime | None = TimestampField(default=None)
    failure_reason: str | None = CharField(250, default=None)
    failed_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )


class SubscriptionControlModel(PersistenceEntity):
    request_key: str = CharField(128, unique=True)
    subscription_id: int = ForeignKeyField("tbl_subscriptions.id", index=True)
    staff_id: int | None = ForeignKeyField("tbl_staff.id", default=None)
    actor_account_id: int | None = ForeignKeyField(
        "tbl_reseller_accounts.id", default=None
    )
    action: str = CharField(16)
    reason: str = CharField(250)
    clock: str | None = CharField(16, default=None)
