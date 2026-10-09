import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.billing.wallet.domain.dtos import TopupCreate
from src.modules.billing.wallet.interfaces import IWalletCommand
from src.modules.sales.checkout.app.errors import (
    checkout_conflict,
)
from src.modules.sales.checkout.domain.contracts import (
    CheckoutCancel,
    CheckoutCapacity,
    CheckoutCreate,
    CheckoutOffer,
    CheckoutReconfirm,
)
from src.modules.sales.checkout.domain.models import CheckoutIntentModel
from src.modules.sales.checkout.infra.mysql import CheckoutIntentRepository
from src.modules.sales.checkout.infra.readers import CheckoutFundingReader
from src.modules.sales.checkout.interfaces import (
    ICheckoutActionReceiptService,
    ICheckoutAttemptService,
    ICheckoutIntentLockCommand,
    ICheckoutNoticeCommand,
    ICheckoutOfferQuery,
    IPurchaseCheckoutPolicyQuery,
)
from src.modules.sales.subscriptions.domain.dtos import SubscriptionCreate
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand


def now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class CheckoutIntentCommand:
    def __init__(
        self,
        intents: CheckoutIntentRepository,
        receipts: ICheckoutActionReceiptService,
        offers: ICheckoutOfferQuery,
        funding: CheckoutFundingReader,
        wallets: IWalletCommand,
        subscriptions: ISubscriptionCommand,
        capacity: CheckoutCapacity,
        policies: IPurchaseCheckoutPolicyQuery,
        customers: ICustomerService,
        attempts: ICheckoutAttemptService,
        locks: ICheckoutIntentLockCommand,
        notices: ICheckoutNoticeCommand,
    ) -> None:
        self.notices = notices
        self.intents, self.offers, self.funding = intents, offers, funding
        self.receipts = receipts
        self.policies = policies
        self.customers, self.attempts, self.locks = customers, attempts, locks
        self.wallets, self.subscriptions, self.capacity = (
            wallets,
            subscriptions,
            capacity,
        )

    @staticmethod
    def check_offer(
        offer: CheckoutOffer, price: int, digest: str, id: int
    ) -> None:
        if offer.price_rial != price or offer.offer_sha256 != digest:
            raise checkout_conflict("checkout_offer_changed", id)

    @staticmethod
    def check_revision(row: CheckoutIntentModel, revision: int) -> None:
        if row.revision != revision:
            raise checkout_conflict("checkout_revision_conflict", row.id)

    @staticmethod
    def request_digest(data: CheckoutCreate) -> str:
        return hashlib.sha256(data.model_dump_json().encode()).hexdigest()

    @handle_conflicts
    @transactional
    async def create(
        self, customer_id: int, data: CheckoutCreate
    ) -> CheckoutIntentModel:
        key = f"checkout:{customer_id}:{data.request_key}"
        digest = await asyncio.to_thread(self.request_digest, data)
        await self.customers.locked(customer_id)
        reservation = await self.attempts.reserve(customer_id, key, digest)
        existing = await self.intents.by_request_key_current(key)
        if existing is not None:
            if (
                existing.customer_id != customer_id
                or existing.body_sha256 != digest
            ):
                raise checkout_conflict(
                    "checkout_request_conflict", existing.id
                )
            await self.attempts.link(reservation, existing.id, digest)
            return existing
        self.attempts.admit(reservation, digest)
        if (
            not self.capacity.minimum_expiry_seconds
            <= data.expiry_seconds
            <= self.capacity.maximum_expiry_seconds
        ):
            raise checkout_conflict("checkout_expiry_capacity", customer_id)
        offer = await self.offers.get(customer_id, data.plan_id)
        self.check_offer(
            offer,
            data.expected_price_rial,
            data.expected_offer_sha256,
            data.plan_id,
        )
        topup = None
        if data.funding_mode == "approved_topup":
            assert data.topup_amount_rial is not None
            topup = await self.wallets.request_topup(
                TopupCreate(
                    customer_id=customer_id,
                    request_key=key,
                    amount_rial=data.topup_amount_rial,
                    destination_id=data.destination_id,
                )
            )
        result = await self.intents.create(
            CheckoutIntentModel(
                customer_id=customer_id,
                request_key=key,
                body_sha256=digest,
                purchase_key=key,
                plan_id=data.plan_id,
                state="awaiting_funding" if topup is not None else "ready",
                funding_mode=data.funding_mode,
                delivery_mode=offer.delivery_mode,
                price_rial=offer.price_rial,
                offer_sha256=offer.offer_sha256,
                auto_renew=data.auto_renew,
                expires_at=now_naive()
                + timedelta(seconds=data.expiry_seconds),
                changed_offer_action=data.changed_offer_action,
                topup_id=topup.id if topup is not None else None,
            )
        )
        await self.attempts.link(reservation, result.id, digest)
        return result

    @transactional
    async def reconfirm(
        self, customer_id: int, id: int, data: CheckoutReconfirm
    ) -> CheckoutIntentModel:
        row = await self.locks.owned(customer_id, id)
        key, digest, replay = await self.receipts.replay(
            row, "reconfirm", data
        )
        if replay:
            return row
        self.check_revision(row, data.expected_revision)
        if (
            row.state != "action_required"
            or row.subscription_id is not None
            or row.expires_at <= now_naive()
        ):
            raise checkout_conflict("checkout_reconfirmation_unavailable", id)
        offer = await self.offers.get(customer_id, row.plan_id)
        self.check_offer(
            offer, data.expected_price_rial, data.expected_offer_sha256, id
        )
        result = await self.intents.update_existing(
            row,
            CheckoutIntentModel.patch(
                revision=row.revision + 1,
                price_rial=offer.price_rial,
                offer_sha256=offer.offer_sha256,
                delivery_mode=offer.delivery_mode,
                state="awaiting_funding"
                if row.topup_id is not None
                else "ready",
                reason_code=None,
                checked_at=None,
            ),
        )
        await self.receipts.record(result, "reconfirm", key, digest)
        return result

    @transactional
    async def cancel(
        self, customer_id: int, id: int, data: CheckoutCancel
    ) -> CheckoutIntentModel:
        row = await self.locks.owned(customer_id, id)
        key, digest, replay = await self.receipts.replay(row, "cancel", data)
        if replay:
            return row
        self.check_revision(row, data.expected_revision)
        if row.subscription_id is not None or row.state in {
            "purchased",
            "expired",
        }:
            raise checkout_conflict("checkout_cancellation_unavailable", id)
        if row.state == "cancelled":
            await self.receipts.record(row, "cancel", key, digest)
            return row
        result = await self.intents.update_existing(
            row,
            CheckoutIntentModel.patch(
                revision=row.revision + 1,
                state="cancelled",
                reason_code="checkout_cancelled",
                checked_at=now_naive(),
            ),
        )
        await self.notices.capture(result)
        await self.receipts.record(result, "cancel", key, digest)
        return result

    @transactional
    async def attempt(self, id: int) -> CheckoutIntentModel:
        row = await self.locks.known(id)
        if row.subscription_id is not None or row.state in {
            "purchased",
            "cancelled",
            "expired",
        }:
            return row
        now = now_naive()
        if row.expires_at <= now:
            result = await self.intents.update_existing(
                row,
                CheckoutIntentModel.patch(
                    revision=row.revision + 1,
                    state="expired",
                    reason_code="checkout_expired",
                    checked_at=now,
                ),
            )
            await self.notices.capture(result)
            return result
        if (
            not (await self.policies.current()).enabled
            or row.state == "action_required"
        ):
            result = await self.intents.update_existing(
                row, CheckoutIntentModel.patch(checked_at=now)
            )
            return result
        offer = await self.offers.get(row.customer_id, row.plan_id)
        self.check_offer(offer, row.price_rial, row.offer_sha256, id)
        if row.topup_id is not None:
            topup = await self.funding.topup_current(
                row.topup_id, row.customer_id
            )
            if topup is None:
                raise checkout_conflict("checkout_topup_unavailable", id)
            if topup.status != "approved":
                result = await self.intents.update_existing(
                    row,
                    CheckoutIntentModel.patch(
                        revision=row.revision + 1
                        if topup.status == "rejected"
                        else row.revision,
                        state="action_required"
                        if topup.status == "rejected"
                        else "awaiting_funding",
                        reason_code="checkout_topup_rejected"
                        if topup.status == "rejected"
                        else None,
                        checked_at=now,
                    ),
                )
                await self.notices.capture(result)
                return result
        balance = await self.funding.balance_current(row.customer_id)
        if balance < row.price_rial:
            result = await self.intents.update_existing(
                row,
                CheckoutIntentModel.patch(
                    state="awaiting_funding",
                    reason_code="wallet_insufficient",
                    checked_at=now,
                ),
            )
            return result
        now = now_naive()
        if row.expires_at <= now:
            result = await self.intents.update_existing(
                row,
                CheckoutIntentModel.patch(
                    revision=row.revision + 1,
                    state="expired",
                    reason_code="checkout_expired",
                    checked_at=now,
                ),
            )
            await self.notices.capture(result)
            return result
        subscription = await self.subscriptions.purchase(
            SubscriptionCreate(
                customer_id=row.customer_id,
                plan_id=row.plan_id,
                expected_price_rial=row.price_rial,
                expected_offer_sha256=row.offer_sha256,
                auto_renew=row.auto_renew,
                purchase_key=row.purchase_key,
            )
        )
        result = await self.intents.update_existing(
            row,
            CheckoutIntentModel.patch(
                revision=row.revision + 1,
                state="purchased",
                subscription_id=subscription.id,
                reason_code=None,
                checked_at=now,
            ),
        )
        return result

    @transactional
    async def record_failure(self, id: int, code: str) -> CheckoutIntentModel:
        """Fresh operation after failed attempt rolled back completely."""
        row = await self.locks.known(id)
        if row.subscription_id is not None or row.state in {
            "purchased",
            "cancelled",
            "expired",
        }:
            return row
        policy = await self.policies.current(locked=True)
        now = now_naive()
        if row.expires_at <= now:
            state = "expired"
            code = "checkout_expired"
        elif (
            code == "checkout_offer_busy"
            and policy.transient_conflict_action == "retry_until_expiry"
        ):
            state = "awaiting_funding" if row.topup_id is not None else "ready"
        else:
            state = (
                "cancelled"
                if code == "checkout_offer_changed"
                and row.changed_offer_action == "cancel"
                else "action_required"
            )
        result = await self.intents.update_existing(
            row,
            CheckoutIntentModel.patch(
                revision=row.revision + 1,
                state=state,
                reason_code=code,
                checked_at=now,
            ),
        )
        await self.notices.capture(result)
        return result
