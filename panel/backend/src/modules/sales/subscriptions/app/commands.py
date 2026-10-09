from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.billing.wallet.app.ledger import ledger_entry
from src.modules.billing.wallet.domain.models import WalletModel
from src.modules.billing.wallet.infra.mysql import WalletRepository
from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.network.ip_limits.domain.models import IpLimitPolicyModel
from src.modules.network.ip_limits.infra.mysql import IpLimitPolicyRepository
from src.modules.network.ip_limits.interfaces import (
    IIpLeaseTrackingService,
    IPurchasedIpPolicyService,
)
from src.modules.network.provisioning.interfaces import IProvisioningCommand
from src.modules.network.routing.interfaces import IHostGroupService
from src.modules.operations.notifications.domain.dtos import (
    NotificationEvent,
    NotificationKind,
)
from src.modules.operations.notifications.interfaces import (
    INotificationCreateCommand,
)
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.catalog.infra.mysql import PlanRepository
from src.modules.sales.checkout.interfaces import ICheckoutProductVerifier
from src.modules.sales.loyalty.interfaces import (
    ICustomerLoyaltyQuery,
    ILoyaltyPolicyService,
    IPurchaseVolumeCommand,
)
from src.modules.sales.reseller_billing.domain.dtos import PurchaseActor
from src.modules.sales.reseller_billing.interfaces import IResellerBillingQuery
from src.modules.sales.subscriptions.domain.dtos import (
    AutoRenewChoice,
    ProvisionFailure,
    SubscriptionCreate,
    SubscriptionSearch,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository
from src.modules.sales.subscriptions.interfaces import (
    ISubscriptionRenewalQuoteQuery,
)


class SubscriptionCommand:
    def __init__(
        self,
        customers: CustomerRepository,
        plans: PlanRepository,
        wallets: WalletRepository,
        subscriptions: SubscriptionRepository,
        settings: PapilioSettings,
        checkout_verifier: ICheckoutProductVerifier,
        groups: IHostGroupService,
        provisioning: IProvisioningCommand,
        preferences: IPreferencesService,
        ip_policies: IpLimitPolicyRepository,
        purchased_ip: IPurchasedIpPolicyService,
        ip_lease_tracking: IIpLeaseTrackingService,
        reseller_billing: IResellerBillingQuery,
        renewal_quotes: ISubscriptionRenewalQuoteQuery,
        loyalty: ICustomerLoyaltyQuery,
        volumes: IPurchaseVolumeCommand,
        loyalty_policy: ILoyaltyPolicyService,
        notifications: INotificationCreateCommand,
    ) -> None:
        self.checkout_verifier = checkout_verifier
        self.customers = customers
        self.plans = plans
        self.wallets = wallets
        self.subscriptions = subscriptions
        self.settings = settings
        self.groups = groups
        self.provisioning = provisioning
        self.preferences = preferences
        self.ip_policies = ip_policies
        self.purchased_ip = purchased_ip
        self.ip_lease_tracking = ip_lease_tracking
        self.reseller_billing = reseller_billing
        self.renewal_quotes = renewal_quotes
        self.loyalty, self.volumes = loyalty, volumes
        self.loyalty_policy, self.notifications = loyalty_policy, notifications

    async def get(self, id: int) -> SubscriptionModel:
        result = await self.subscriptions.get_by_id(id)
        if result is None:
            raise _missing(id)
        return result

    @handle_conflicts
    @transactional
    async def purchase(
        self, data: SubscriptionCreate, *, actor: PurchaseActor | None = None
    ) -> SubscriptionModel:
        existing = await self.subscriptions.by_purchase_key(data.purchase_key)
        if existing is not None:
            if (
                existing.entitlement_kind != "paid"
                or existing.customer_id != data.customer_id
                or existing.plan_id != data.plan_id
            ):
                raise _conflict(
                    "کلید خرید برای درخواست دیگری استفاده شده است.",
                    "purchase_key_reused",
                    existing.id,
                )
            await self.reseller_billing.replay(existing, actor)
            return existing
        billing = await self.reseller_billing.purchase(data, actor)
        customer = await self.customers.locked(data.customer_id)
        if (
            customer is None
            or not customer.is_active
            or not CustomerAccessPolicy.services_available(customer)
        ):
            raise _conflict(
                "مشتری فعال نیست.", "customer_inactive", data.customer_id
            )
        plan = (
            billing.agreement.plan
            if billing is not None
            else await self.plans.locked(data.plan_id)
        )
        if plan is None or not plan.is_active:
            raise _conflict("پلن فعال نیست.", "plan_inactive", data.plan_id)
        commerce = (
            None
            if billing is not None
            else await self.loyalty.quote(customer.id, plan.id, locked=True)
        )
        price = (
            billing.price_rial
            if billing is not None
            else commerce.price_rial
            if commerce is not None
            else plan.price_rial
        )
        payer_id = (
            billing.payer_customer_id if billing is not None else customer.id
        )
        if payer_id != customer.id:
            payer = await self.customers.locked(payer_id)
            if payer is None or not CustomerAccessPolicy.services_available(
                payer
            ):
                raise _conflict(
                    "حساب پرداخت‌کننده فعال نیست.", "payer_inactive", payer_id
                )
        if (
            data.expected_price_rial is not None
            and price != data.expected_price_rial
        ):
            raise _conflict(
                "قیمت پلن تغییر کرده است؛ قیمت تازه را بررسی کنید.",
                "purchase_price_changed",
                plan.id,
            )
        captured_preferences = None
        if data.expected_offer_sha256 is not None:
            if billing is not None or commerce is None:
                raise _conflict(
                    "Checkout payer mode is unsupported",
                    "checkout_reseller_funding_unsupported",
                    plan.id,
                )
            captured_preferences = (
                await self.preferences.current(locked=True)
            ).values
            await self.checkout_verifier.verify(
                customer.id,
                plan,
                commerce,
                captured_preferences,
                data.expected_offer_sha256,
            )
        if plan.group_id is not None:
            group = await self.groups.get(plan.group_id)
            if not group.is_enabled:
                raise _conflict(
                    "گروه تحویل پلن غیرفعال است.",
                    "plan_group_disabled",
                    plan.id,
                )
        wallet = await self.wallets.locked_for_customer(
            WalletModel(customer_id=payer_id, balance_rial=0)
        )
        if wallet.balance_rial < price:
            raise _conflict(
                "موجودی کیف پول کافی نیست.", "wallet_insufficient", customer.id
            )
        now = datetime.now(UTC).replace(tzinfo=None)
        fulfillment = (
            FulfillmentPolicy.model_validate_json(plan.fulfillment_json)
            if plan.fulfillment_json is not None
            else (
                captured_preferences
                or (await self.preferences.current()).values
            ).fulfillment
            or self.settings.fulfillment.policy
        )
        subscription = await self.subscriptions.create(
            SubscriptionModel(
                quota_policy_json=(
                    QuotaPolicy.model_validate_json(plan.quota_policy_json)
                    if plan.quota_policy_json is not None
                    else (
                        captured_preferences
                        or (await self.preferences.current()).values
                    ).quota_policy
                    or self.settings.usage.policy
                ).model_dump_json(),
                fulfillment_json=fulfillment.model_dump_json(),
                provisioning_managed=True,
                purchase_key=data.purchase_key,
                customer_id=customer.id,
                payer_customer_id=payer_id,
                reseller_id=billing.reseller.id
                if billing is not None
                else None,
                reseller_agreement_id=billing.agreement.agreement.id
                if billing is not None
                else None,
                reseller_billing_json=billing.snapshot.model_dump_json()
                if billing is not None
                else None,
                commerce_json=commerce.model_dump_json()
                if commerce is not None
                else None,
                plan_id=plan.id,
                group_id=plan.group_id,
                quota_bytes=plan.quota_bytes,
                base_quota_bytes=plan.quota_bytes,
                price_rial=price,
                duration_days=plan.duration_days,
                expires_at=None
                if plan.duration_days is None
                else now + timedelta(days=plan.duration_days),
                status="pending_provision",
                auto_renew=data.auto_renew,
                renewal_count=0,
            )
        )
        await self.wallets.record(
            wallet,
            ledger_entry(
                wallet,
                -price,
                f"purchase:{subscription.id}",
                "purchase",
            ),
        )
        if billing is None:
            await self.volumes.record(
                customer.id,
                subscription.id,
                0,
                plan.id,
                plan.quota_bytes,
                price,
                commerce,
            )
        if commerce is not None and commerce.discount_rial > 0:
            policy = (await self.loyalty_policy.current()).values
            if policy.notify_discounts:
                await self.notifications.enqueue(
                    customer.id,
                    NotificationEvent(
                        event_key=f"discount:{subscription.id}:0",
                        kind=NotificationKind.DISCOUNT_APPLIED,
                        record_id=subscription.id,
                        amount_rial=commerce.discount_rial,
                        status=commerce.tier_code or "first_purchase",
                    ),
                )
        default_ip = (
            captured_preferences or (await self.preferences.current()).values
        ).ip_defaults
        ip_policy = (
            IpLimitChoice.model_validate_json(plan.ip_limit_json)
            if plan.ip_limit_json is not None
            else IpLimitChoice.model_validate(default_ip.model_dump())
        )
        await self.purchased_ip.capture(
            subscription.id,
            plan.id,
            ip_policy,
            "plan_override"
            if plan.ip_limit_json is not None
            else "purchase_defaults",
        )
        await self.ip_lease_tracking.initialize_purchase(subscription.id)
        if plan.ip_limit_json is not None or ip_policy.enabled:
            await self.ip_policies.create(
                IpLimitPolicyModel(
                    subscription_id=subscription.id, **ip_policy.model_dump()
                )
            )
        await self.provisioning.queue(
            subscription.id, subscription.renewal_count, fulfillment
        )
        return subscription

    @transactional
    async def set_auto_renew(
        self, id: int, data: AutoRenewChoice
    ) -> SubscriptionModel:
        subscription = await self.subscriptions.locked(id)
        if subscription is None:
            raise _missing(id)
        if data.enabled and subscription.entitlement_kind == "trial":
            raise _conflict(
                "اشتراک آزمایشی تمدید خودکار ندارد.", "trial_not_renewable", id
            )
        if subscription.status in {"cancelled", "failed"}:
            raise _conflict(
                "اشتراک قابل تمدید نیست.", "subscription_not_renewable", id
            )
        result = await self.subscriptions.update_existing(
            subscription, SubscriptionModel.patch(auto_renew=data.enabled)
        )
        return result

    @transactional
    async def customer_set_auto_renew(
        self, id: int, customer_id: int, data: AutoRenewChoice
    ) -> SubscriptionModel:
        observed = await self.get(id)
        if observed.customer_id != customer_id:
            raise _missing(id)
        await self.reseller_billing.customer_renewal_choice(
            observed, data.enabled
        )
        subscription = await self.subscriptions.locked(id)
        if subscription is None or subscription.customer_id != customer_id:
            raise _missing(id)
        if data.enabled and subscription.entitlement_kind == "trial":
            raise _conflict(
                "اشتراک آزمایشی تمدید خودکار ندارد.", "trial_not_renewable", id
            )
        if subscription.status in {"cancelled", "failed"}:
            raise _conflict(
                "اشتراک قابل تمدید نیست.", "subscription_not_renewable", id
            )
        result = await self.subscriptions.update_existing(
            subscription, SubscriptionModel.patch(auto_renew=data.enabled)
        )
        return result

    @handle_conflicts
    @transactional
    async def reseller_set_auto_renew(
        self, id: int, principal: ResellerPrincipal, data: AutoRenewChoice
    ) -> SubscriptionModel:
        observed = await self.get(id)
        await self.reseller_billing.reseller_renewal_choice(
            observed, principal
        )
        subscription = await self.subscriptions.locked(id)
        if subscription is None:
            raise _missing(id)
        if data.enabled and subscription.entitlement_kind == "trial":
            raise _conflict(
                "اشتراک آزمایشی تمدید خودکار ندارد.", "trial_not_renewable", id
            )
        if subscription.status in {"cancelled", "failed"}:
            raise _conflict(
                "اشتراک قابل تمدید نیست.", "subscription_not_renewable", id
            )
        result = await self.subscriptions.update_existing(
            subscription, SubscriptionModel.patch(auto_renew=data.enabled)
        )
        return result

    @handle_conflicts
    @transactional
    async def fail_provision(
        self, id: int, data: ProvisionFailure, staff_id: int
    ) -> SubscriptionModel:
        hint = await self.subscriptions.get_by_id(id)
        if hint is None:
            raise _missing(id)
        customer_id = hint.customer_id
        payer_customer_id = hint.payer_customer_id
        payer_id = payer_customer_id or customer_id
        if payer_id != customer_id:
            await self.customers.locked_many(
                sorted([customer_id, payer_id]), ascending=True
            )
        else:
            await self.customers.locked(customer_id)
        subscription = await self.subscriptions.locked(id)
        if subscription is None:
            raise _missing(id)
        if (
            subscription.customer_id != customer_id
            or subscription.payer_customer_id != payer_customer_id
        ):
            raise _conflict(
                "مالک یا پرداخت‌کنندهٔ اشتراک هنگام انتظار تغییر کرده است.",
                "subscription_owner_changed",
                id,
            )
        if subscription.status == "failed":
            return subscription
        if subscription.status != "pending_provision":
            raise _conflict(
                "اشتراک در انتظار راه‌اندازی نیست.",
                "subscription_not_pending",
                id,
            )
        if subscription.activated_at is not None:
            raise _conflict(
                "اشتراک قبلاً فعال شده و این عملیات بازگشت خرید اولیه نیست.",
                "subscription_already_activated",
                id,
            )
        if subscription.provisioning_managed:
            await self.provisioning.cancel(
                id, subscription.renewal_count, data.reason, staff_id
            )
            result = await self.get(id)
            return result
        wallet = await self.wallets.locked_for_customer(
            WalletModel(
                customer_id=payer_id,
                balance_rial=0,
            )
        )
        await self.wallets.record(
            wallet,
            ledger_entry(
                wallet,
                subscription.price_rial,
                f"provision_refund:{id}:{subscription.renewal_count}",
                "provision_refund",
            ),
        )
        await self.volumes.reverse(subscription.id, subscription.renewal_count)
        result = await self.subscriptions.update_existing(
            subscription,
            SubscriptionModel.patch(
                status="failed",
                auto_renew=False,
                failure_reason=data.reason,
                failed_by_staff_id=staff_id,
            ),
        )
        return result

    @handle_conflicts
    @transactional
    async def renew_due(self, id: int) -> SubscriptionModel:
        hint = await self.subscriptions.get_by_id(id)
        if hint is None:
            raise _missing(id)
        customer_id = hint.customer_id
        customer = await self.customers.locked(customer_id)
        subscription = await self.subscriptions.locked(id)
        if subscription is None:
            raise _missing(id)
        if subscription.customer_id != customer_id:
            raise _conflict(
                "مالک اشتراک هنگام انتظار تغییر کرده است.",
                "subscription_owner_changed",
                id,
            )
        now = datetime.now(UTC).replace(tzinfo=None)
        if subscription.entitlement_kind == "trial":
            return subscription
        if not subscription.auto_renew or subscription.status not in {
            "active",
            "expired",
            "exhausted",
        }:
            return subscription
        fulfillment = (
            FulfillmentPolicy.model_validate_json(
                subscription.fulfillment_json
            )
            if subscription.fulfillment_json is not None
            else (await self.preferences.current()).values.fulfillment
            or self.settings.fulfillment.policy
        )
        due_expiry = (
            subscription.expires_at is not None
            and subscription.expires_at <= now
        ) and fulfillment.renewal_trigger in {"expiry", "either"}
        due_quota = (
            subscription.quota_bytes is not None
            and subscription.used_bytes >= subscription.quota_bytes
        ) and fulfillment.renewal_trigger in {"quota", "either"}
        if not due_expiry and not due_quota:
            result = await self.subscriptions.update_existing(
                subscription, SubscriptionModel.patch(renewal_checked_at=now)
            )
            return result
        quote = await self.renewal_quotes.get(subscription, locked=True)
        if not quote.available:
            result = await self.subscriptions.update_existing(
                subscription, SubscriptionModel.patch(renewal_checked_at=now)
            )
            return result
        if customer is None or not CustomerAccessPolicy.renewals_available(
            customer
        ):
            result = await self.subscriptions.update_existing(
                subscription, SubscriptionModel.patch(renewal_checked_at=now)
            )
            return result
        payer_id = subscription.payer_customer_id or subscription.customer_id
        if payer_id != subscription.customer_id:
            payer = await self.customers.locked(payer_id)
            if payer is None or not CustomerAccessPolicy.renewals_available(
                payer
            ):
                result = await self.subscriptions.update_existing(
                    subscription,
                    SubscriptionModel.patch(renewal_checked_at=now),
                )
                return result
        if subscription.provisioning_managed:
            retired = await self.provisioning.retire(
                subscription.id,
                subscription.renewal_count,
                "expire"
                if (
                    subscription.expires_at is not None
                    and subscription.expires_at <= now
                )
                else "quota",
                "تمدید پس از پایان دوره",
                None,
            )
            if retired.state != "revoked":
                return subscription
        wallet = await self.wallets.locked_for_customer(
            WalletModel(customer_id=payer_id, balance_rial=0)
        )
        reference = f"renewal:{id}:{subscription.renewal_count + 1}"
        price = quote.price_rial
        if wallet.balance_rial < price:
            result = await self.subscriptions.update_existing(
                subscription,
                SubscriptionModel.patch(
                    status="expired"
                    if (
                        subscription.expires_at is not None
                        and subscription.expires_at <= now
                    )
                    else "exhausted",
                    renewal_checked_at=now,
                ),
            )
            return result
        await self.wallets.record(
            wallet,
            ledger_entry(wallet, -price, reference, "auto_renewal"),
        )
        result = await self.subscriptions.update_existing(
            subscription,
            SubscriptionModel.patch(
                expires_at=None
                if subscription.duration_days is None
                else now + timedelta(days=subscription.duration_days),
                renewal_count=subscription.renewal_count + 1,
                status="pending_provision",
                renewal_checked_at=now,
                fulfillment_json=fulfillment.model_dump_json(),
                provisioning_managed=True,
                price_rial=price,
                commerce_json=quote.commerce.model_dump_json()
                if quote.commerce is not None
                else subscription.commerce_json,
                base_quota_bytes=subscription.base_quota_bytes
                or subscription.quota_bytes,
                quota_bytes=None
                if subscription.quota_bytes is None
                else (
                    subscription.base_quota_bytes or subscription.quota_bytes
                )
                + max(subscription.quota_bytes - subscription.used_bytes, 0)
                if fulfillment.renewal_quota == "carry_unused"
                else (
                    subscription.base_quota_bytes or subscription.quota_bytes
                ),
                used_bytes=0,
                activated_at=None,
            ),
        )
        if result.reseller_id is None:
            await self.volumes.record(
                result.customer_id,
                result.id,
                result.renewal_count,
                result.plan_id,
                result.base_quota_bytes,
                price,
                quote.commerce,
            )
        await self.provisioning.queue(
            result.id, result.renewal_count, fulfillment
        )
        return result

    async def search(
        self, data: SubscriptionSearch
    ) -> ServicePage[SubscriptionModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.subscriptions.page(
            data.customer_id,
            data.status,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)


def _missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="اشتراک پیدا نشد.",
        message_code="subscription_not_found",
        entity="subscription",
        identifier="id",
        identifier_value=id,
    )


def _conflict(message: str, code: str, id: int) -> ConflictException:
    return ConflictException(
        message=message, message_code=code, unique_dict={"id": id}
    )
