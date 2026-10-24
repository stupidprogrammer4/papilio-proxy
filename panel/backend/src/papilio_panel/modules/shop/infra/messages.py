"""Native encrypted message outbox, scoped metadata and conditional send leases."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from papilio_panel.modules.bots.domain import TelegramSendResult
from papilio_panel.shared.errors import Conflict, Missing

from ..domain import (
    InvoiceReplyLookup,
    MessageClaim,
    MessageRead,
    MessageState,
    ReplyWrite,
    ShopSettingsRead,
    WorkDelivery,
)
from ..models import MessageRecovery, OutgoingMessage
from ..recovery_contracts import (
    MessageRecoveryRead,
    MessageRecoveryReservation,
    MessageRecoveryWrite,
)
from .recovery_audits import message_recovery_read
from .replies import decrypt_reply, encrypt_reply


def message_read(row: OutgoingMessage) -> MessageRead:
    return MessageRead(
        row.id,
        row.event_id,
        row.bot_id,
        row.owner_id,
        row.administrator,
        MessageState(row.status),
        row.attempts,
        row.message_id,
        row.error_code,
        row.retry_at,
        row.created_at,
        row.lease_until,
        row.revision,
        row.invoice_id,
    )


def scoped_messages() -> QuerySet[OutgoingMessage]:
    return OutgoingMessage.objects.filter(owner_id=F("bot__owner_id"), event__bot_id=F("bot_id"))


class DjangoShopMessageStorage:
    def recovery(self, actor_id: int, request_key: UUID) -> MessageRecoveryRead | None:
        try:
            row = MessageRecovery.objects.get(actor_id=actor_id, request_key=request_key)
        except MessageRecovery.DoesNotExist:
            return None
        return message_recovery_read(row)

    @transaction.atomic
    def recover(self, values: MessageRecoveryWrite) -> MessageRecoveryReservation:
        inputs = values.values
        definition = inputs.definition
        row, created = MessageRecovery.objects.get_or_create(
            actor_id=inputs.actor_id,
            request_key=definition.request_key,
            defaults={
                "bot_id": inputs.bot_id,
                "message_id": inputs.message_id,
                "expected_revision": definition.expected_revision,
                "action": definition.action,
                "note": definition.note,
                "previous_status": values.previous.status,
                "previous_attempts": values.previous.attempts,
            },
        )
        if created:
            scoped_ids = scoped_messages().filter(bot__owner_id=inputs.actor_id).values("pk")
            updated = OutgoingMessage.objects.filter(
                pk=inputs.message_id,
                pk__in=scoped_ids,
                bot_id=inputs.bot_id,
                owner_id=inputs.actor_id,
                revision=definition.expected_revision,
            ).update(
                status=values.status,
                revision=F("revision") + 1,
                attempts=values.attempts,
                error_code=values.error_code,
                retry_at=None,
                lease_token=None,
                lease_until=None,
                dispatched_at=None,
            )
            if updated != 1:
                raise Conflict("The outgoing message changed before recovery committed.")
        return MessageRecoveryReservation(message_recovery_read(row), created)

    def append(self, values: ReplyWrite) -> UUID:
        ciphertext = encrypt_reply(values.reply)
        if values.source_event_id is not None:
            row, _ = OutgoingMessage.objects.get_or_create(
                source_event_id=values.source_event_id,
                defaults={
                    "event_id": values.event_id,
                    "bot_id": values.bot_id,
                    "owner_id": values.owner_id,
                    "administrator": values.administrator,
                    "invoice_id": values.invoice_id,
                    "payload_ciphertext": ciphertext,
                },
            )
            if (
                row.event_id != values.event_id
                or row.bot_id != values.bot_id
                or row.owner_id != values.owner_id
                or row.invoice_id != values.invoice_id
                or row.administrator != values.administrator
            ):
                raise Conflict("The notification event already belongs to a different destination.")
        else:
            row = OutgoingMessage.objects.create(
                event_id=values.event_id,
                bot_id=values.bot_id,
                owner_id=values.owner_id,
                administrator=values.administrator,
                invoice_id=values.invoice_id,
                payload_ciphertext=ciphertext,
            )
        return row.id

    def reference(self, message_id: UUID) -> MessageRead:
        try:
            row = scoped_messages().defer("payload_ciphertext").get(pk=message_id)
        except OutgoingMessage.DoesNotExist as error:
            raise Missing("The outgoing bot message was not found.") from error
        return message_read(row)

    def read(self, message_id: UUID, bot_id: UUID, owner_id: int) -> MessageRead:
        result = self.reference(message_id)
        if result.bot_id != bot_id or result.owner_id != owner_id:
            raise Missing("The outgoing message was not found on this bot.")
        return result

    @transaction.atomic
    def claim(
        self, message_id: UUID, settings: ShopSettingsRead, lease_seconds: int
    ) -> MessageClaim | None:
        now, token = timezone.now(), uuid4()
        eligible = Q(status=MessageState.QUEUED) | Q(status=MessageState.RETRY, retry_at__lte=now)
        updated = OutgoingMessage.objects.filter(
            eligible, pk=message_id, bot_id=settings.bot_id, owner_id=settings.owner_id
        ).update(
            status=MessageState.SENDING,
            revision=F("revision") + 1,
            lease_token=token,
            lease_until=now + timedelta(seconds=lease_seconds),
            attempts=F("attempts") + 1,
        )
        if not updated:
            return None
        row = OutgoingMessage.objects.get(
            pk=message_id, bot_id=settings.bot_id, owner_id=settings.owner_id, lease_token=token
        )
        values = ReplyWrite(
            row.event_id,
            row.bot_id,
            row.owner_id,
            decrypt_reply(bytes(row.payload_ciphertext)),
            row.administrator,
            row.invoice_id,
            row.source_event_id,
        )
        return MessageClaim(row.id, token, row.attempts, values, settings)

    def complete(
        self,
        claim: MessageClaim,
        result: TelegramSendResult,
        status: MessageState,
        retry_at: datetime | None,
    ) -> None:
        OutgoingMessage.objects.filter(
            pk=claim.id, lease_token=claim.token, status=MessageState.SENDING
        ).update(
            status=status,
            revision=F("revision") + 1,
            retry_at=retry_at,
            message_id=result.message_id,
            chat_id=result.chat_id,
            error_code=result.error_code,
            lease_token=None,
            lease_until=None,
        )

    def expire(self, message_id: UUID, status: MessageState, retry_at: datetime | None) -> None:
        OutgoingMessage.objects.filter(
            pk=message_id, status=MessageState.SENDING, lease_until__lt=timezone.now()
        ).update(
            status=status,
            revision=F("revision") + 1,
            retry_at=retry_at,
            error_code="sender_lease_expired",
            lease_token=None,
            lease_until=None,
            dispatched_at=None,
        )

    def release(self, claim: MessageClaim) -> None:
        OutgoingMessage.objects.filter(
            pk=claim.id, lease_token=claim.token, status=MessageState.SENDING
        ).update(
            status=MessageState.QUEUED,
            revision=F("revision") + 1,
            attempts=F("attempts") - 1,
            lease_token=None,
            lease_until=None,
            dispatched_at=None,
            retry_at=None,
        )

    def active(self, claim: MessageClaim) -> bool:
        return (
            scoped_messages()
            .filter(
                pk=claim.id,
                bot_id=claim.values.bot_id,
                owner_id=claim.values.owner_id,
                event_id=claim.values.event_id,
                status=MessageState.SENDING,
                lease_token=claim.token,
                lease_until__gt=timezone.now(),
            )
            .exists()
        )

    def reject(self, message_id: UUID, error_code: str) -> None:
        OutgoingMessage.objects.filter(
            pk=message_id, status__in=[MessageState.QUEUED, MessageState.RETRY]
        ).update(status=MessageState.FAILED, error_code=error_code, revision=F("revision") + 1)

    def pending(self) -> tuple[WorkDelivery, ...]:
        now = timezone.now()
        before = now - timedelta(seconds=settings.PAPILIO_OUTBOX_REDELIVERY_SECONDS)
        pending = Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=before)
        active = (
            Q(status=MessageState.QUEUED)
            | Q(status=MessageState.RETRY, retry_at__lte=now)
            | Q(status=MessageState.SENDING, lease_until__lt=now)
        )
        rows = (
            scoped_messages()
            .filter(
                pending,
                active,
                bot__shop_configuration__enabled=True,
                bot__shop_configuration__delivery_enabled=True,
                bot__periodic_task__enabled=True,
            )
            .select_related("bot")
            .defer("payload_ciphertext")
            .order_by("created_at", "id")[: settings.PAPILIO_OUTBOX_BATCH_SIZE]
        )
        return tuple(WorkDelivery(row.id, 2 * row.bot.http_timeout_seconds + 30) for row in rows)

    def dispatched(self, deliveries: tuple[WorkDelivery, ...]) -> None:
        OutgoingMessage.objects.filter(pk__in=[item.id for item in deliveries]).update(
            dispatched_at=timezone.now()
        )

    def invoice_for_reply(self, values: InvoiceReplyLookup) -> UUID:
        origins = scoped_messages().filter(
            bot_id=values.bot_id,
            owner_id=values.owner_id,
            chat_id=values.telegram_user_id,
            message_id=values.message_id,
            administrator=False,
            status=MessageState.SENT,
            invoice_id__isnull=False,
        )
        try:
            origin = origins.get()
        except OutgoingMessage.DoesNotExist as error:
            raise Missing(
                "The replied-to bot message has no payment invoice in this chat."
            ) from error
        if origin.invoice_id is None:
            raise Missing("The replied-to bot message has no payment invoice.")
        return origin.invoice_id
