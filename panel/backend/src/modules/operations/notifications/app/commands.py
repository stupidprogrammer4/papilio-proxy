import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import ConflictException, ValidationException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256

from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.operations.notifications.app.queries import (
    missing_notification,
)
from src.modules.operations.notifications.domain.context import (
    CheckoutNoticeAction,
    SubscriptionNoticeAction,
)
from src.modules.operations.notifications.domain.dtos import (
    DeliveryStatus,
    ManualNotificationCreate,
    NotificationChannelMode,
    NotificationEvent,
    NotificationKind,
    NotificationRecovery,
)
from src.modules.operations.notifications.domain.models import (
    NotificationAttemptModel,
    NotificationModel,
    NotificationRecoveryModel,
)
from src.modules.operations.notifications.domain.results import (
    DeliveryOutcome,
    NotificationClaim,
)
from src.modules.operations.notifications.infra.mysql import (
    NotificationAttemptRepository,
    NotificationRecoveryRepository,
    NotificationRepository,
)
from src.modules.operations.notifications.interfaces import (
    INotificationPolicyQuery,
)
from src.modules.sales.checkout.interfaces import ICheckoutNoticeSourceQuery
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class NotificationCreateCommand:
    def __init__(
        self,
        repo: NotificationRepository,
        customers: CustomerRepository,
        policy: INotificationPolicyQuery,
    ) -> None:
        self.repo, self.customers, self.policy = repo, customers, policy

    @handle_conflicts
    @transactional
    async def enqueue(
        self, customer_id: int, data: NotificationEvent
    ) -> NotificationModel:
        fingerprint = await asyncio.to_thread(
            hash_sha256, data.model_dump_json()
        )
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise unavailable_customer(customer_id)
        existing = await self.repo.by_request(customer_id, data.event_key)
        if existing is not None:
            if existing.event_hash != fingerprint:
                raise changed("notification_event_reused", existing.id)
            return existing
        current = await self.policy.current()
        template = current.values.templates.get(data.kind)
        values = {
            "id": str(data.record_id),
            "amount_toman": toman_text(data.amount_rial)
            if data.amount_rial is not None
            else "",
            "status": data.status,
            "quota_gib": "",
            "used_gib": "",
            "remaining_gib": "",
            "expires_at": "",
            "renewal_price_toman": "",
            "generation": "",
            "threshold_code": "",
        }
        title, body = (
            template.title.format_map(values) if template is not None else "",
            template.body.format_map(values) if template is not None else "",
        )
        enabled = (
            current.values.enabled
            and template is not None
            and template.enabled
            and current.capacity_valid
            and len(title) <= 160
            and len(title + "\n" + body) <= current.values.max_message_chars
        )
        row = await self.repo.ensure(
            NotificationModel(
                customer_id=customer_id,
                event_key=data.event_key,
                event_hash=fingerprint,
                kind=data.kind,
                record_id=data.record_id,
                title=title,
                body=body,
                inbox_visible=enabled
                and current.values.channel_mode
                != NotificationChannelMode.TELEGRAM,
                status=DeliveryStatus.PENDING
                if enabled
                and current.values.channel_mode
                != NotificationChannelMode.INBOX
                else DeliveryStatus.SKIPPED,
                next_attempt_at=datetime.now(UTC).replace(
                    tzinfo=None, microsecond=0
                ),
                error_code=None if enabled else "notification_suppressed",
            )
        )
        if row.event_hash != fingerprint:
            raise changed("notification_event_reused", row.id)
        return row

    @handle_conflicts
    @transactional
    async def manual(
        self, customer_id: int, data: ManualNotificationCreate, staff_id: int
    ) -> NotificationModel:
        fingerprint = await asyncio.to_thread(
            hash_sha256, data.model_dump_json()
        )
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise unavailable_customer(customer_id)
        existing = await self.repo.by_request(
            customer_id, "manual:" + data.request_key
        )
        if existing is not None:
            if (
                existing.event_hash != fingerprint
                or existing.created_by_staff_id != staff_id
            ):
                raise changed("notification_event_reused", existing.id)
            return existing
        current = await self.policy.current()
        title = (
            data.title
            if data.title is not None
            else current.values.templates[NotificationKind.MANUAL].title
        )
        body = (
            data.body
            if data.body is not None
            else current.values.templates[NotificationKind.MANUAL].body
        )
        if (
            not current.capacity_valid
            or not current.values.enabled
            or not current.values.templates[NotificationKind.MANUAL].enabled
        ):
            raise invalid("notification_disabled")
        if (
            not title.strip()
            or not body.strip()
            or len(title + "\n" + body) > current.values.max_message_chars
        ):
            raise invalid("notification_message_length")
        row = await self.repo.ensure(
            NotificationModel(
                customer_id=customer_id,
                event_key="manual:" + data.request_key,
                created_by_staff_id=staff_id,
                event_hash=fingerprint,
                kind=NotificationKind.MANUAL,
                title=title,
                body=body,
                inbox_visible=current.values.channel_mode
                != NotificationChannelMode.TELEGRAM,
                status=DeliveryStatus.PENDING
                if current.values.channel_mode != NotificationChannelMode.INBOX
                else DeliveryStatus.SKIPPED,
                next_attempt_at=datetime.now(UTC).replace(
                    tzinfo=None, microsecond=0
                ),
            )
        )
        if (
            row.event_hash != fingerprint
            or row.created_by_staff_id != staff_id
        ):
            raise changed("notification_event_reused", row.id)
        return row


class NotificationInboxCommand:
    def __init__(self, repo: NotificationRepository) -> None:
        self.repo = repo

    @transactional
    async def set_read(
        self, id: int, customer_id: int, is_read: bool
    ) -> NotificationModel:
        row = await self.repo.locked(id)
        if (
            row is None
            or row.customer_id != customer_id
            or not row.inbox_visible
        ):
            raise missing_notification(id)
        result = await self.repo.update_existing(
            row, NotificationModel.patch(is_read=is_read)
        )
        return result


class NotificationDeliveryCommand:
    def __init__(
        self,
        repo: NotificationRepository,
        attempts: NotificationAttemptRepository,
        recoveries: NotificationRecoveryRepository,
        customers: CustomerRepository,
        policy: INotificationPolicyQuery,
        subscriptions: SubscriptionRepository,
        checkout_sources: ICheckoutNoticeSourceQuery,
    ) -> None:
        self.checkout_sources = checkout_sources
        self.subscriptions = subscriptions
        (
            self.repo,
            self.attempts,
            self.recoveries,
            self.customers,
            self.policy,
        ) = repo, attempts, recoveries, customers, policy

    @transactional
    async def claim(self, id: int) -> NotificationClaim | None:
        row = await self.repo.locked(id)
        if row is None:
            raise missing_notification(id)
        current = await self.policy.current()
        template = current.values.templates.get(NotificationKind(row.kind))
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if (
            row.status == DeliveryStatus.PROCESSING
            and row.lease_until is not None
            and row.lease_until <= now
        ):
            attempt = await self.attempts.by_claim(id, row.claim_token or "")
            if attempt is not None:
                await self.attempts.update_existing(
                    attempt,
                    NotificationAttemptModel.patch(
                        outcome="ambiguous",
                        error_code="delivery_lease_expired",
                        finished_at=now,
                    ),
                )
            status = (
                DeliveryStatus.RETRY
                if current.values.ambiguous_mode == "retry"
                and row.retry_budget_used < current.values.max_attempts
                else DeliveryStatus.AMBIGUOUS
            )
            row = await self.repo.update_existing(
                row,
                NotificationModel.patch(
                    status=status,
                    claim_token=None,
                    lease_until=None,
                    error_code="delivery_lease_expired",
                    next_attempt_at=now
                    + timedelta(seconds=current.values.retry_seconds),
                    revision=row.revision + 1,
                ),
            )
        if (
            not current.capacity_valid
            or not current.values.enabled
            or template is None
            or not template.enabled
            or not current.values.delivery_enabled
            or not current.outbound_available
        ):
            return None
        if (
            row.status not in {DeliveryStatus.PENDING, DeliveryStatus.RETRY}
            or row.next_attempt_at is None
            or row.next_attempt_at > now
        ):
            return None
        customer = await self.customers.get_by_id(row.customer_id)
        if (
            customer is None
            or not customer.is_active
            or customer.telegram_id is None
        ):
            await self.repo.update_existing(
                row,
                NotificationModel.patch(
                    status=DeliveryStatus.FAILED,
                    error_code="notification_recipient_unavailable",
                    revision=row.revision + 1,
                ),
            )
            return None
        if row.retry_budget_used >= current.values.max_attempts:
            await self.repo.update_existing(
                row,
                NotificationModel.patch(
                    status=DeliveryStatus.FAILED,
                    error_code="delivery_attempts_exhausted",
                    revision=row.revision + 1,
                ),
            )
            return None
        if len(row.title + "\n" + row.body) > current.values.max_message_chars:
            await self.repo.update_existing(
                row,
                NotificationModel.patch(
                    status=DeliveryStatus.FAILED,
                    error_code="notification_message_length",
                    revision=row.revision + 1,
                ),
            )
            return None
        attempt_number = row.attempts + 1
        token = secrets.token_hex(32)
        lease = now + timedelta(seconds=current.values.lease_seconds)
        await self.repo.update_existing(
            row,
            NotificationModel.patch(
                status=DeliveryStatus.PROCESSING,
                claim_token=token,
                lease_until=lease,
                attempts=attempt_number,
                retry_budget_used=row.retry_budget_used + 1,
                error_code=None,
                revision=row.revision + 1,
            ),
        )
        await self.attempts.create(
            NotificationAttemptModel(
                notification_id=id,
                attempt=attempt_number,
                claim_token=token,
                outcome="started",
            )
        )
        return NotificationClaim(
            id, token, customer.telegram_id, row.title + "\n" + row.body, lease
        )

    @transactional
    async def begin_send(
        self, id: int, token: str
    ) -> NotificationClaim | None:
        observed = await self.repo.get_by_id(id)
        action: SubscriptionNoticeAction | CheckoutNoticeAction | None = None
        customer = None
        checkout_notice = observed is not None and observed.kind in {
            NotificationKind.CHECKOUT_ACTION_REQUIRED,
            NotificationKind.CHECKOUT_CANCELLED,
            NotificationKind.CHECKOUT_EXPIRED,
        }
        if checkout_notice:
            assert observed is not None
            customer = await self.customers.locked(observed.customer_id)
            if customer is None or observed.record_id is None:
                return None
            action = await self.checkout_sources.owned(
                observed.customer_id, observed.record_id
            )
            if action is None:
                return None
        elif (
            observed is not None
            and observed.subscription_context is not None
            and observed.record_id is not None
        ):
            source = await self.subscriptions.locked(observed.record_id)
            if (
                source is not None
                and source.customer_id == observed.customer_id
            ):
                action = SubscriptionNoticeAction(subscription_id=source.id)
        row = await self.repo.locked(id)
        if row is None:
            return None
        if checkout_notice and (
            observed is None
            or row.customer_id != observed.customer_id
            or row.record_id != observed.record_id
            or row.kind != observed.kind
        ):
            return None
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        current = await self.policy.current(locked=True)
        template = current.values.templates.get(NotificationKind(row.kind))
        if (
            not current.capacity_valid
            or not current.values.enabled
            or template is None
            or not template.enabled
            or not current.values.delivery_enabled
            or not current.outbound_available
            or row.status != DeliveryStatus.PROCESSING
            or row.claim_token != token
            or row.lease_until is None
            or row.lease_until <= now
        ):
            return None
        attempt = await self.attempts.by_claim(id, token)
        if attempt is None or attempt.outcome != "started":
            return None
        if customer is None:
            customer = await self.customers.locked(row.customer_id)
        if (
            customer is None
            or not customer.is_active
            or customer.telegram_id is None
        ):
            return None
        await self.attempts.update_existing(
            attempt, NotificationAttemptModel.patch(outcome="sending")
        )
        return NotificationClaim(
            id,
            token,
            customer.telegram_id,
            row.title + "\n" + row.body,
            row.lease_until,
            action,
        )

    @transactional
    async def finish(
        self, id: int, token: str, outcome: DeliveryOutcome
    ) -> bool:
        row = await self.repo.locked(id)
        if row is None:
            raise missing_notification(id)
        if row.status != DeliveryStatus.PROCESSING or row.claim_token != token:
            return False
        current = await self.policy.current()
        attempt = await self.attempts.by_claim(id, token)
        assert attempt is not None
        if outcome.outcome == "accepted" and (
            attempt.outcome != "sending" or outcome.message_id is None
        ):
            outcome = DeliveryOutcome(
                "ambiguous", "notification_send_unconfirmed"
            )
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        status = (
            DeliveryStatus.DELIVERED
            if outcome.outcome == "accepted"
            else DeliveryStatus.AMBIGUOUS
            if outcome.outcome == "ambiguous"
            else DeliveryStatus.FAILED
        )
        can_retry = (
            outcome.outcome == "retryable"
            or outcome.outcome == "ambiguous"
            and current.values.ambiguous_mode == "retry"
        )
        if can_retry and row.retry_budget_used < current.values.max_attempts:
            status = DeliveryStatus.RETRY
        p = current.values
        delay = min(
            p.max_retry_seconds,
            p.retry_seconds
            * (
                2
                ** min(
                    row.retry_budget_used - 1, p.max_retry_seconds.bit_length()
                )
                if p.backoff_mode == "exponential"
                else 1
            ),
        )
        error_code = outcome.error_code
        if outcome.retry_after_seconds is not None:
            if outcome.retry_after_seconds > p.max_retry_seconds:
                status = DeliveryStatus.FAILED
                error_code = "notification_retry_after_capacity"
            else:
                delay = max(delay, outcome.retry_after_seconds)
        await self.attempts.update_existing(
            attempt,
            NotificationAttemptModel.patch(
                outcome=outcome.outcome,
                error_code=outcome.error_code,
                finished_at=now,
            ),
        )
        await self.repo.update_existing(
            row,
            NotificationModel.patch(
                status=status,
                claim_token=None,
                lease_until=None,
                telegram_message_id=outcome.message_id,
                error_code=error_code,
                next_attempt_at=now + timedelta(seconds=delay)
                if status == DeliveryStatus.RETRY
                else None,
                revision=row.revision + 1,
            ),
        )
        return True

    @transactional
    async def recover(
        self, id: int, staff_id: int, data: NotificationRecovery
    ) -> NotificationModel:
        row = await self.repo.locked(id)
        if row is None:
            raise missing_notification(id)
        if row.revision != data.expected_revision:
            raise changed("notification_changed", id)
        if row.status not in {
            DeliveryStatus.FAILED,
            DeliveryStatus.AMBIGUOUS,
            DeliveryStatus.RETRY,
            DeliveryStatus.PENDING,
        }:
            raise changed("notification_recovery_unavailable", id)
        await self.recoveries.create(
            NotificationRecoveryModel(
                notification_id=id,
                revision=row.revision + 1,
                staff_id=staff_id,
                action=data.action,
                previous_status=row.status,
                reason=data.reason,
            )
        )
        result = await self.repo.update_existing(
            row,
            NotificationModel.patch(
                status=DeliveryStatus.PENDING
                if data.action == "retry"
                else DeliveryStatus.CANCELLED,
                next_attempt_at=datetime.now(UTC).replace(
                    tzinfo=None, microsecond=0
                )
                if data.action == "retry"
                else None,
                retry_budget_used=0
                if data.action == "retry"
                else row.retry_budget_used,
                error_code=None,
                revision=row.revision + 1,
            ),
        )
        return result


def changed(code: str, id: int) -> ConflictException:
    return ConflictException(
        message="وضعیت اعلان تغییر کرده یا این عملیات در دسترس نیست.",
        message_code=code,
        unique_dict={"id": id},
    )


def invalid(code: str) -> ValidationException:
    return ValidationException(
        message="سیاست یا متن اعلان اجازهٔ ثبت نمی‌دهد.",
        message_code=code,
        loc=["notification"],
        input=None,
    )


def unavailable_customer(id: int) -> ValidationException:
    return ValidationException(
        message="مشتری اعلان پیدا نشد.",
        message_code="notification_customer_unavailable",
        loc=["customer_id"],
        input=id,
    )


def toman_text(rial: int) -> str:
    whole, fraction = divmod(rial, 10)
    return str(whole) + ("." + str(fraction) if fraction else "")
