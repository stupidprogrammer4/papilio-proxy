"""Scoped native ORM projections for work, outgoing metadata and recovery history."""

from uuid import UUID

from django.db.models import Q

from papilio_panel.shared.errors import Missing

from ..domain import MessageRead, WorkState
from ..models import InboxWork, MessageRecovery, OutgoingMessage, WorkRecovery
from ..recovery_contracts import (
    InspectionWindow,
    MessagePage,
    MessageRecoveryPage,
    MessageSearch,
    WorkInspection,
    WorkPage,
    WorkRecoveryPage,
    WorkSearch,
)
from .messages import message_read, scoped_messages
from .recovery_audits import message_recovery_read, work_recovery_read


def work_inspection(row: InboxWork) -> WorkInspection:
    return WorkInspection(
        row.id,
        row.event_id,
        row.event.bot.id,
        WorkState(row.status),
        row.revision,
        row.attempts,
        row.error_code,
        row.retry_at,
        row.lease_until,
        row.event.received_at,
        row.completed_at,
    )


class DjangoWorkInspectionReader:
    def read(self, bot_id: UUID, work_id: UUID, actor_id: int) -> WorkInspection:
        try:
            row = InboxWork.objects.select_related("event__bot").get(
                pk=work_id,
                event__bot_id=bot_id,
                event__bot__owner_id=actor_id,
            )
        except InboxWork.DoesNotExist as error:
            raise Missing("The conversation work was not found on this bot.") from error
        return work_inspection(row)

    def search(self, values: WorkSearch) -> WorkPage:
        rows = InboxWork.objects.select_related("event__bot").filter(
            event__bot_id=values.bot_id,
            event__bot__owner_id=values.actor_id,
        )
        if values.status is not None:
            rows = rows.filter(status=values.status)
        if values.query:
            rows = rows.filter(
                Q(id__icontains=values.query) | Q(error_code__icontains=values.query)
            )
        count = rows.count()
        offset = (values.page - 1) * values.page_size
        selected = rows.order_by("-event__received_at", "-id")[offset : offset + values.page_size]
        return WorkPage(
            tuple(work_inspection(row) for row in selected), count, values.page, values.page_size
        )

    def history(self, work_id: UUID, values: InspectionWindow) -> WorkRecoveryPage:
        rows = WorkRecovery.objects.filter(
            work_id=work_id,
            bot_id=values.bot_id,
            bot__owner_id=values.actor_id,
            work__event__bot_id=values.bot_id,
        )
        if values.query:
            rows = rows.filter(
                Q(note__icontains=values.query)
                | Q(action__icontains=values.query)
                | Q(id__icontains=values.query)
            )
        count = rows.count()
        offset = (values.page - 1) * values.page_size
        selected = rows.order_by("-created_at", "-id")[offset : offset + values.page_size]
        return WorkRecoveryPage(
            tuple(work_recovery_read(row) for row in selected), count, values.page, values.page_size
        )


class DjangoMessageInspectionReader:
    def read(self, bot_id: UUID, message_id: UUID, actor_id: int) -> MessageRead:
        try:
            row = (
                scoped_messages()
                .defer("payload_ciphertext")
                .get(
                    pk=message_id,
                    bot_id=bot_id,
                    owner_id=actor_id,
                    bot__owner_id=actor_id,
                )
            )
        except OutgoingMessage.DoesNotExist as error:
            raise Missing("The outgoing message was not found on this bot.") from error
        return message_read(row)

    def search(self, values: MessageSearch) -> MessagePage:
        rows = (
            scoped_messages()
            .defer("payload_ciphertext")
            .filter(
                bot_id=values.bot_id,
                owner_id=values.actor_id,
                bot__owner_id=values.actor_id,
            )
        )
        if values.status is not None:
            rows = rows.filter(status=values.status)
        if values.query:
            rows = rows.filter(
                Q(id__icontains=values.query) | Q(error_code__icontains=values.query)
            )
        count = rows.count()
        offset = (values.page - 1) * values.page_size
        selected = rows.order_by("-created_at", "-id")[offset : offset + values.page_size]
        return MessagePage(
            tuple(message_read(row) for row in selected), count, values.page, values.page_size
        )

    def history(self, message_id: UUID, values: InspectionWindow) -> MessageRecoveryPage:
        rows = MessageRecovery.objects.filter(
            message_id=message_id,
            bot_id=values.bot_id,
            bot__owner_id=values.actor_id,
            message__bot_id=values.bot_id,
            message__owner_id=values.actor_id,
        )
        if values.query:
            rows = rows.filter(
                Q(note__icontains=values.query)
                | Q(action__icontains=values.query)
                | Q(id__icontains=values.query)
            )
        count = rows.count()
        offset = (values.page - 1) * values.page_size
        selected = rows.order_by("-created_at", "-id")[offset : offset + values.page_size]
        return MessageRecoveryPage(
            tuple(message_recovery_read(row) for row in selected),
            count,
            values.page,
            values.page_size,
        )
