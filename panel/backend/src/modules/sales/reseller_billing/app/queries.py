from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.app.policies import (
    ResellerCapacity,
    ResellerDelegation,
    conflict,
)
from src.modules.accounts.resellers.domain.dtos import ResellerPolicy
from src.modules.accounts.resellers.domain.models import ResellerModel
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.accounts.staff.infra.readers import StaffAuthorityReader
from src.modules.sales.reseller_billing.domain.dtos import (
    PurchaseActor,
    ResellerBillingSnapshot,
)
from src.modules.sales.reseller_billing.domain.results import (
    PurchaseBilling,
    RenewalBilling,
)
from src.modules.sales.reseller_billing.infra.readers import (
    ResellerBillingReader,
)
from src.modules.sales.reseller_catalog.app.pricing import AgreementPricing
from src.modules.sales.reseller_catalog.domain.dtos import AgreementPrice
from src.modules.sales.reseller_catalog.infra.readers import ResellerPlanReader
from src.modules.sales.subscriptions.domain.dtos import SubscriptionCreate
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


class ResellerBillingQuery:
    def __init__(
        self,
        reader: ResellerBillingReader,
        agreements: ResellerPlanReader,
        staff_authority: StaffAuthorityReader,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.agreements = agreements
        self.staff_authority = staff_authority
        self.settings = settings

    async def _authority(
        self, customer_id: int, actor: PurchaseActor | None
    ) -> ResellerModel | None:
        staff = None
        if actor is not None and actor.staff_id is not None:
            staff = await self.staff_authority.access(actor.staff_id, True)
            if (
                staff is None
                or not staff.staff.is_active
                or not staff.effective_scopes
                & {"*", "subscriptions:*", "subscriptions:create"}
            ):
                raise conflict("subscription_purchase_denied")
        reseller = await self.reader.owner(customer_id, True)
        if staff is not None and reseller is not None:
            ResellerDelegation.staff(staff, "manage")
        if actor is not None and actor.reseller is not None:
            principal = actor.reseller
            if reseller is None or reseller.id != principal.reseller_id:
                raise conflict("reseller_customer_not_owned")
            account = await self.reader.account(
                reseller.id, principal.account_id
            )
            ResellerDelegation.principal(
                reseller,
                account,
                principal,
                "subscriptions:create",
                self.settings,
            )
        return reseller

    async def purchase(
        self, data: SubscriptionCreate, actor: PurchaseActor | None
    ) -> PurchaseBilling | None:
        reseller = await self._authority(data.customer_id, actor)
        if reseller is None:
            return None
        capacity = ResellerCapacity.configured(self.settings)
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        ResellerCapacity.validate(policy, capacity)
        if not capacity.enabled or not reseller.sales_enabled:
            raise conflict("reseller_sales_disabled")
        self_purchase = actor is None or (
            actor.staff_id is None and actor.reseller is None
        )
        if self_purchase:
            if not policy.customer_self_purchase:
                raise conflict("reseller_customer_purchase_disabled")
            payer_mode = "customer_wallet"
        else:
            assert actor is not None
            payer_mode = actor.payer_mode
            if payer_mode is None and policy.payer_mode != "either":
                payer_mode = policy.payer_mode
        if payer_mode is None:
            raise conflict("reseller_payer_required")
        if policy.payer_mode != "either" and policy.payer_mode != payer_mode:
            raise conflict("reseller_payer_denied")
        facts = await self.agreements.for_plan(reseller.id, data.plan_id, True)
        if (
            facts is None
            or not facts.agreement.enabled
            or not facts.plan.is_active
        ):
            raise conflict("reseller_plan_unavailable")
        price = AgreementPrice.model_validate_json(facts.agreement.price_json)
        return PurchaseBilling(
            reseller=reseller,
            payer_customer_id=reseller.wallet_customer_id
            if payer_mode == "reseller_wallet"
            else data.customer_id,
            agreement=facts,
            price_rial=AgreementPricing.quote(price, facts.plan.price_rial),
            snapshot=ResellerBillingSnapshot(
                agreement_revision=facts.agreement.revision,
                price=price,
                payer_mode=payer_mode,
                renewal_price_mode=policy.renewal_price_mode,
                renewal_availability_mode=policy.renewal_availability_mode,
            ),
        )

    async def replay(
        self, subscription: SubscriptionModel, actor: PurchaseActor | None
    ) -> None:
        reseller = await self._authority(subscription.customer_id, actor)
        if subscription.reseller_id != (reseller.id if reseller else None):
            raise conflict("reseller_purchase_owner_changed")
        if actor is not None and actor.payer_mode is not None:
            if subscription.reseller_billing_json is None:
                raise conflict("purchase_key_reused")
            snapshot = ResellerBillingSnapshot.model_validate_json(
                subscription.reseller_billing_json
            )
            if actor.payer_mode != snapshot.payer_mode:
                raise conflict("purchase_key_reused")

    async def renewal(
        self, subscription: SubscriptionModel
    ) -> RenewalBilling | None:
        if subscription.reseller_id is None:
            return None
        reseller = await self.reader.owner(subscription.customer_id, True)
        if reseller is None or reseller.id != subscription.reseller_id:
            raise conflict("reseller_purchase_owner_changed")
        capacity = self.settings.resellers
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        if (
            capacity is None
            or not capacity.enabled
            or not reseller.renewals_enabled
            or not ResellerCapacity.valid(policy, capacity)
        ):
            return RenewalBilling(False, subscription.price_rial)
        if subscription.reseller_billing_json is None:
            raise conflict("reseller_billing_snapshot_missing")
        snapshot = ResellerBillingSnapshot.model_validate_json(
            subscription.reseller_billing_json
        )
        price = subscription.price_rial
        if (
            snapshot.renewal_availability_mode == "current_agreement"
            or snapshot.renewal_price_mode == "current_agreement"
        ):
            facts = await self.agreements.for_plan(
                reseller.id, subscription.plan_id, True
            )
            if (
                facts is None
                or facts.agreement.id != subscription.reseller_agreement_id
            ):
                return RenewalBilling(False, price)
            if snapshot.renewal_availability_mode == "current_agreement" and (
                not facts.agreement.enabled or not facts.plan.is_active
            ):
                return RenewalBilling(False, price)
            if snapshot.renewal_price_mode == "current_agreement":
                price = AgreementPricing.quote(
                    AgreementPrice.model_validate_json(
                        facts.agreement.price_json
                    ),
                    facts.plan.price_rial,
                )
        return RenewalBilling(True, price)

    async def customer_renewal_choice(
        self, subscription: SubscriptionModel, enabled: bool
    ) -> None:
        if (
            subscription.reseller_id is None
            or (subscription.payer_customer_id or subscription.customer_id)
            == subscription.customer_id
        ):
            return
        reseller = await self.reader.owner(subscription.customer_id, True)
        if reseller is None or reseller.id != subscription.reseller_id:
            raise conflict("reseller_purchase_owner_changed")
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        if enabled or not policy.customer_can_disable_reseller_renewal:
            raise conflict("reseller_customer_renewal_denied")

    async def reseller_renewal_choice(
        self, subscription: SubscriptionModel, principal: ResellerPrincipal
    ) -> None:
        reseller = await self.reader.owner(subscription.customer_id, True)
        if reseller is None or reseller.id != principal.reseller_id:
            raise conflict("reseller_customer_not_owned")
        account = await self.reader.account(reseller.id, principal.account_id)
        ResellerDelegation.principal(
            reseller, account, principal, "subscriptions:update", self.settings
        )
